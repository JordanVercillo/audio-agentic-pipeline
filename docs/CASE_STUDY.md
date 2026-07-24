# Case study — Vercillo Analytics

*A personal music-analytics platform built after Spotify deleted the API it would
have depended on — and the AI-assisted engineering methodology that built it.*

**Live:** [vercilloanalytics.com](https://vercilloanalytics.com) ·
**Author:** Jordan Vercillo · **Cost:** $0/month · **Tests:** 579, synthetic-only

---

## 1. The problem: the API disappeared

In November 2024 and again in February 2026, Spotify removed the Web API
surfaces this kind of project traditionally consumed: `/audio-features`,
`/audio-analysis`, recommendations, related artists, artist top-tracks
("no replacement available"), all batch endpoints, and most metadata fields —
for exactly the development-mode apps a personal project can be.

Every taste-analytics project that *consumed* those columns died. The answer
here was to become the **producer**:

> Acquire the audio itself, extract a controlled feature space with local DSP,
> and warehouse it — so the acoustic intelligence is *owned*, not rented.

That decision shaped everything downstream: the dataset is rebuildable from
scratch, the feature contract is frozen and versioned, and no product surface
can be killed by a vendor deprecation again. The deprecations that remain in
play are handled by an explicit **borrowed-time doctrine** (§4).

## 2. The system

```
Spotify (PKCE, metadata only)      YouTube (yt-dlp, duration-verified match)
      │ top tracks · playlists          │ transient audio — deleted after DSP
      ▼                                 ▼
  STAGING (Bronze) ──► CLEANSED (Silver) ──► MODELED (Gold star schema)
                          77-dim librosa vector (frozen contract)
                                        │
                        ┌───────────────┴────────────────┐
                        ▼                                ▼
              SQLite+WAL serving cache          MCP server (read-only DuckDB,
              + DB-as-queue worker               2-layer SQL security)
                        ▼
              FastAPI app — dashboard · analytics · artists ·
              library · playlists · recommendations · RAG ask-box
```

- **One bridge key.** `spotify_track_id` is the *only* join key across
  metadata, audio filenames (`{id}.mp3` — the filename *is* the key), features,
  and the star schema. No second ID system exists anywhere.
- **Two data planes.** The medallion warehouse (Parquet, pyarrow) serves batch
  analytics and agents; a SQLite+WAL cache serves the live app, with a
  DB-as-queue extraction worker draining download+DSP jobs (~50 s/track,
  idempotent, dead-lettered on repeated failure, self-healing after crashes).
- **The DSP layer is the product.** 77 dimensions of tempo, energy, timbre,
  harmony — plus derived display series (loudness curves, beat grids,
  self-similarity sections) that rebuild what Spotify's `/audio-analysis` used
  to expose, from audio we analyzed ourselves. Audio is transient: features and
  spectrograms are the durable artifacts; the MP3 is deleted after extraction.

## 3. Provenance: making the corpus honest

Becoming the producer created a producer's problem: **where did each track's
audio actually come from, and is it the right song?** The corpus grew by
matching Spotify metadata to YouTube uploads — and a matcher that only *ranks*
will always return its least-bad guess, so an obscure track can silently
acquire a two-hour DJ set or a same-length wrong song. Auditing the corpus by
hand found exactly that: 27 wrong-song acquisitions and 19 mix-length ones.

The fix is a data-quality spine, not a patch:

- **Lineage at event grain.** Every acquisition writes an append-only
  `track_provenance` row — source URL, channel, the matcher and its version,
  match confidence, the duration delta against Spotify's own length. Nothing
  the matcher knew is discarded. The `/song` page surfaces it as a one-click
  "open the source and judge it yourself"; `/library` shows a per-row glyph.
- **One acceptance gate, shared by every path.** Selection and *admissibility*
  are different jobs: the matcher ranks, a single `match_gate` decides what may
  become a track's audio at all (title containment, leading-artist attribution,
  two-sided duration, reproduction-marker rejection). The live worker and the
  batch re-extraction runner call the *same* gate — the earlier split, where
  only the runner had guards, is precisely how the bad rows got in.
- **Withhold, don't guess.** A track with no verified source has its features
  withheld — from the display **and** from the clusters, percentiles, marts and
  chat. Numbers the app won't show a visitor can't be allowed to shape the
  archetype it shows them. A fail-safe caps the rule: with no lineage data at
  all, it withholds *nothing*, so an empty table can never silently empty the
  corpus.
- **A regression sweep over live data.** `qa_audit.py` runs the whole class of
  fixes — duration sanity, the affinity check, plane coherence, and a
  *behavioural* test that drives the real worker path and asserts it refuses a
  DJ set — against the production corpus, and exits non-zero on any failure.

The outcome is a number the platform can stand behind: **100% of the
aggregate corpus traces to a verified source**, and the remaining unverified
tracks are visibly, honestly withheld rather than quietly averaged in.

## 4. Production at $0

The app serves real multi-user traffic from a residential PC:

- **No client secret exists** — anywhere, ever. Auth is session-scoped PKCE;
  the browser holds a signed session-id cookie, tokens stay server-side and
  expire. The one credential in `.env` is a *public* client id.
- **Cloudflare Tunnel** carries the domain to localhost; an **origin-fallback
  Worker** turns "the PC is off" into an honest *"this demo runs on-demand"*
  page instead of a dead link — the on-demand posture is a stated design
  decision, not an outage.
- **Access is tiered honestly:** the corpus (library, per-song acoustic
  deep-dives, the live analysis queue) is public with no login; "View as
  guest" replays the owner's own dashboard read-only from a snapshot with
  zero API calls; five dev-mode pilot seats get the personalized end-to-end
  experience, including capped, membership-checked playlist imports.
- **Operations are deterministic:** `app-verify` (live-system flags),
  `warehouse-audit` (bridge-key integrity, exact feature-contract
  verification), cache backup on every stop, and a public `/queue` page that
  shows the worker's true FIFO state.

## 5. Doctrines the build earned

Each of these came out of a real incident, is written down as a numbered
journal lesson, and is enforced somewhere in code or tests:

| Doctrine | Origin |
|---|---|
| **Borrowed-time garnish.** Endpoints removed on paper but still answering may vanish mid-request: they may decorate a page, never carry it. Derived views (e.g. "*your* top tracks by this artist," from ranks we already store) are the load-bearing core. | journal #29 |
| **Research the surface before you spec the feature.** The artist-page design flipped when a research pass found its intended endpoint was already gone. | journal #29 |
| **Derive, don't transcribe.** Any page or snapshot that re-states computed values is a second copy of the rules and will eventually lie. The guest dashboard renders from ids + the cache, not from carried display fields. | journals #27, P3.5 |
| **Flag, don't delete.** Near-duplicate recordings are annotated (`duplicate_of`) and skipped by intake guards; nothing is merged and no id is ever minted or destroyed. Deletion is an irreversible owner decision. | D-28 |
| **Validate the type the contract requires, not truthiness.** pandas turns `None` into a *truthy* `nan`; a bridge key is a non-empty string, and only `isinstance` checks catch the difference. | journal #30 |
| **Re-derive alarms when a feature changes "normal."** A queue-stuck monitor calibrated for a near-empty queue false-alarmed on the first healthy 100-track import backlog; it now alerts on stalled progress, never on the size of a working backlog. | journal #31 |
| **Estimator honesty.** Detected song sections are labeled by self-similarity only ("the same letter means the same-sounding part") — no "chorus/verse" claims the signal can't support; drift is an effect size, not a vibe. | journals #19, #21, #24 |
| **A resume marker records that work happened, not that it was right.** A re-extraction that "completed" still had to be re-audited against the *current* acceptance bar; correctness is a separate claim from completion. | journal #46 |
| **Rank and admit are different functions.** A system that only ranks returns its least-bad answer as if it were good. Filter every candidate through the gate *before* ranking — judging only the winner both hides the alternatives and makes the bar look more expensive than it is. | journal #48 |
| **An exclusion rule must not be able to exclude everything.** A filter defined by subtraction inherits the failure modes of the set it subtracts from; "exclude the unverified" needs a floor, or an empty verification table wipes the corpus. | journal #50 |

## 6. The methodology: AI-assisted engineering with a paper trail

The repo's second product is *how it was built*. Development ran as a
disciplined human+AI loop (Claude Code), and the harness is committed:

- **Living memory.** Every session starts by reading
  `notes/PROJECT_CONTEXT.md` (verified status, next action, key-files map) and
  ends with a wrap that updates it, so context survives across sessions and
  models. Claims require evidence — test counts, commit hashes, audit output —
  before they may be written down as done.
- **Deterministic audits as skills.** `warehouse-audit` and `app-verify` are
  scripts, not vibes: the session loop is *build → audit → only then claim*.
- **Domain-expert agents with charters.** Small, scoped advisors (webapp,
  data-platform, DSP, LLM/RAG, research, delivery-coach) that cite line
  numbers, attack their own plans, and never commit. A research agent's first
  outing reshaped a feature by discovering its target endpoint no longer
  existed.
- **Model routing as an engineering decision.** Frontier-model budget goes to
  design, security-adversarial review, and irreversibles; well-specced
  execution slices run on a cheaper tier. The routing table lives in the spec,
  per upcoming slice.
- **A numbered lessons journal.** Fifty entries of *genuine surprises
  only* — each one situation → realization → transferable rule. Several are
  now enforced by tripwire tests.

The claim this substantiates isn't "AI wrote the code." It's that a solo
engineer can run a **governed engineering organization** — specs with numbered
decisions, advisory review, deterministic quality gates, and a memory system —
at the cost of one person's attention.

## 7. Numbers

| | |
|---|---|
| Acoustic corpus | **771** analyzed tracks (grown by real users + playlist imports); **731** with a verified audio source shape every aggregate, 40 withheld until repaired |
| Provenance | **100%** of the aggregate corpus traces to a recorded YouTube source (append-only lineage, one click to verify) |
| Feature space | 77-dim frozen vector · 82 numeric feature columns · a reproducible batch star-schema snapshot (118 tracks) feeds the MCP layer |
| Tests | **579**, all synthetic-data — no credentials or network needed; CI green on every push |
| Serving | ~50 s/track download+DSP, serial worker, capped imports (100/playlist) |
| Cost | $0/month (residential hosting, Cloudflare free tier, no paid APIs) |
| Users | 5 PKCE pilot seats (Spotify dev-mode ceiling) + unlimited anonymous browsing |

## 8. Shipped since, and what's next

**Shipped:** a grounded, injection-gated, logged **"talk to your data" chat**
(evals designed before the thing they judge; a read-only SQL tool loop over the
semantic marts behind a binary never-averaged injection gate); the full
**provenance & data-quality spine** of §3; and the **catalog-plane
unification** — one exporter materializes the batch star-schema's `dim_tracks` +
track-grain fact straight from the serving cache, so the MCP layer reads the
same canonical corpus the app serves, with a `GOLD_PLANE_STALE` audit check
holding the two in agreement. The temporal-drift fact behind the taste map
stays a point-in-time snapshot on purpose: its grain is per-user listening rank,
which can't be honestly reproduced for the user-agnostic grown corpus. Chat runs
on a local model at $0.

**Next:**
- **The Million Playlist Dataset at Spark scale** — 66M real playlist-track
  rows for co-occurrence marts and track2vec embeddings, unlocked only when
  real data volume demands it (the honest at-scale benchmark, not a synthetic one).
- **An ML capstone** on the owned feature space — the entire point of
  becoming the producer.

---

*The decision log (D-1…D-57), phase plan, and acceptance criteria live in
[`docs/VISION_SPECS.md`](VISION_SPECS.md) and
[`notes/PROJECT_CONTEXT.md`](../notes/PROJECT_CONTEXT.md); the lessons in
[`notes/engineering_journal.md`](../notes/engineering_journal.md).*
