# Case study — Vercillo Analytics

*A personal music-analytics platform built after Spotify deleted the API it would
have depended on — and the AI-assisted engineering methodology that built it.*

**Live:** [vercilloanalytics.com](https://vercilloanalytics.com) ·
**Author:** Jordan Vercillo · **Cost:** $0/month · **Tests:** 417, synthetic-only

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

## 3. Production at $0

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

## 4. Doctrines the build earned

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

## 5. The methodology: AI-assisted engineering with a paper trail

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
- **A numbered lessons journal.** Thirty-one entries of *genuine surprises
  only* — each one situation → realization → transferable rule. Several are
  now enforced by tripwire tests.

The claim this substantiates isn't "AI wrote the code." It's that a solo
engineer can run a **governed engineering organization** — specs with numbered
decisions, advisory review, deterministic quality gates, and a memory system —
at the cost of one person's attention.

## 6. Numbers

| | |
|---|---|
| Acoustic corpus | 161 real tracks (grown by real users + playlist imports), 160 fully analyzed |
| Feature space | 77-dim frozen vector · 82 numeric feature columns in the gold fact |
| Tests | 417, all synthetic-data — no credentials or network needed |
| Serving | ~50 s/track download+DSP, serial worker, capped imports (100/playlist) |
| Cost | $0/month (residential hosting, Cloudflare free tier, no paid APIs) |
| Users | 5 PKCE pilot seats (Spotify dev-mode ceiling) + unlimited anonymous browsing |

## 7. What's next

- **Agentic chat over the warehouse** (design-first: evals before the thing
  they judge) and **multimodal upload** — users analyze their *own* audio files,
  the legally cleanest acquisition path there is.
- **The Million Playlist Dataset at Spark scale** — 66M real playlist-track
  rows for co-occurrence marts and track2vec embeddings, unlocked only when
  real data volume demands it.
- **An ML capstone** on the owned feature space — the entire point of
  becoming the producer.

---

*The decision log (D-1…D-41), phase plan, and acceptance criteria live in
[`docs/VISION_SPECS.md`](VISION_SPECS.md); the session-by-session arc in
[`docs/SESSION_CHRONICLE.md`](SESSION_CHRONICLE.md); the lessons in
[`notes/engineering_journal.md`](../notes/engineering_journal.md).*
