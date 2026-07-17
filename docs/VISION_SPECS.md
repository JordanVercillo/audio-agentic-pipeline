# Vision Specs & Value Audit — the two candidate directions (2026-07-08)

**Context.** All epics A–E of [`APP_SPEC.md`](APP_SPEC.md) are built and live at
`vercilloanalytics.com`. Two candidate visions for what's next; this doc specs
both and audits **aggro** (effort/risk/annoyance) vs **value** (user experience
+ portfolio signal). Decision framework: the portfolio lens (pipelines, data
quality, DX, AI-on-data-infrastructure) + the $0 local-first constraint (D-16).

---

## Vision A — KB-driven LLM engineering upgrades

**Source.** `llm_knowledge_base/` (synced 2026.07.07): 7 proven technique
cards from the *Foundations of Language Models* course. Reviewed card-by-card
against the live app; the honest finding is that Vision A is **not one product
— it's three surgical upgrades and two deliberate rejections.**

### A1 — Gold eval set for `/ask` + `/classify` ⭐ (the keeper)

Per the `gold-eval-sets` card: the LLM surfaces currently have **zero
measurement instrument** — we can't tell if a prompt/grounding change helps.

- **Build:** `evals/golden_taste.jsonl` (n≈15–20, versioned): fixed synthetic
  taste contexts → expected-answer *facts* (not prose): must-cite entities,
  must-not-invent list, archetype name. A **deterministic grader** (regex/set
  membership — no LLM judge needed at this size) scores the deterministic
  fallback AND the LLM path; report disaggregated per question type next to a
  trivial baseline. CI job runs the fallback path on every push ($0, no key).
- **Teacher-propose → human-verify** (per the distillation card) to grow the
  set later; leakage-guard by id and name.
- **Why it matters:** "LLM evals" is the strongest hiring signal in the
  agent-engineering conversation right now, and the card's method is exactly
  the credible version: versioned set, majority-class baseline, per-dimension
  disaggregation.

### A2 — Structured output contracts for the LLM calls (small, do with A1)

Per `structured-output-json`: `TasteRAG._llm_answer/classify` currently parse
prose. Move both to a JSON schema (`thoughts` field ordered FIRST, then
`answer`, `cited_entities`) — giving the grader (A1) machine-checkable
citations and killing a whole class of parse flakiness. Include the card's
gotchas: fence-stripping, never-swallow-parse-errors-silently.

### A3 — Ollama local-LLM path (✅ DONE 2026-07-11)

**Status: SHIPPED. `WEBAPP_LLM_MODEL=ollama:gemma4:12b` routes /ask + /classify
to the local model ($0, no key); the deterministic fallback is the automatic
safety net; the model warms on webapp startup (avoids the ~90s cold load).**
The F0 golden evals ran exactly as intended: gemma4 first scored **5/15** (vs
the deterministic template's 15/15), failing `must_cite` by paraphrasing labels
and not naming artists — so the grounding contract was tightened (name real
artists/tracks; reuse labelled results VERBATIM), recovering to **9/15**
(must_cite 4→8, classify 1→3; no_invention 15/15, archetype 5/5 throughout —
zero hallucination). **Owner decision (measured, not vibes): ship gemma4 as
the live default** — the misses are paraphrases not fabrications, and the warm
prose beats the template. Journal #25. Original validated plan below.

- **Hardware:** RTX 4070 Ti, 12,282 MiB VRAM (≈3.9 GB resident desktop use).
  Ollama 0.31.1 installed and serving.
- **Installed models (validated via `ollama list`):** gemma4:12b (7.6 GB),
  gemma4:e4b/latest (9.6 GB), gemma3:12b, qwen3:8b (5.2 GB), qwen2.5vl:7b
  (vision), gemma2:2b, nomic-embed-text, recipe-classifier v3/v4 (course
  artifacts).
- **Model choice (owner: "use gemma4"):** **`gemma4:12b`** — best quality that
  fits VRAM. `gemma4:e4b` (9.6 GB) would spill to CPU on this card; retire
  `gemma2:2b` from this role. **`qwen3:8b`** is the fast fallback.
- **Live smoke finding:** default load ran **29% CPU / 71% GPU** — Ollama's
  262,144-token default context inflates the KV cache past free VRAM. Fix:
  request `options={"num_ctx": 8192}` (grounding is ~2K tokens) → weights + KV
  fit fully on-GPU. Also: gemma4:12b is a **thinking model** — pair
  `format="json"` (Ollama enforces valid JSON) with the A2 schema's
  `thoughts`-field-first pattern so reasoning lands inside the contract.
- **Implementation sketch (one slice, later):** `rag.py` routes on
  `WEBAPP_LLM_MODEL=ollama:gemma4:12b` → `ollama.chat(model=…,
  format="json", options={"num_ctx": 8192, "temperature": 0}, keep_alive=…)`;
  same A2 schema + parser; deterministic fallback unchanged. Teacher role
  (golden-answer proposals for A1) = same gemma4:12b + **human verify** — the
  distillation card's same-family-bias caveat applies, the verify pass is the
  guard.

### Deliberate rejections (the KB's own lessons argue against)

- **Vector-store RAG for `/ask`** — the `rag-and-retrieval` card: *"small
  corpora of structured rows don't need vectors"* and *"bad retrieval is
  negative information."* Our grounding is a per-user structured context that
  fits in one prompt; chromadb here is résumé theater. **No.**
- **Fine-tuning an adapter** — prompting hasn't plateaued (barely explored);
  the `finetuning-data-design` card's own precondition fails. **Not now.**
- **Teacher-labeling track moods from metadata** — journal #9 already proved
  the metadata is too sparse to teach anything. **No.**

**Aggro/value:** A1+A2 = **low aggro, high value** (2–3 slices, all synthetic,
CI-friendly). A3 = medium aggro, medium-high value, cleanly separable.

---

## Vision B — The Audio-Feature Explorer + derived perceptual features ⭐⭐

**The vision (Jordan):** analytic datasets → an interactive dashboard where a
user picks an audio feature (danceability, loudness, time signature…) and
explores charts + visual clustering around it.

**The narrative unlock.** Spotify's `get-audio-features` is **officially
Deprecated** (verified today — banner on the reference page). The 13 fields it
served are beloved and gone. **We rebuild them from raw audio** on our own DSP
— with honest confidence tiers — and let users explore ALL our features, not
just 13. That's the whole project's thesis ("the deprecation promoted us from
consumer to producer," journal #1) made user-visible.

### B1 — The derived perceptual feature layer (`perceptual-v1`)

A **pure transform over the cached 82 columns** — no re-extraction, applies
instantly to every cached track, versioned like a model:

| Spotify field | Tier | Derivation from our features |
|---|---|---|
| tempo | ✅ measured | `tempo_bpm` (have) |
| key / mode | ✅ measured | `estimated_key` / `estimated_mode` (have) |
| duration | ✅ measured | `duration_sec` / metadata `duration_ms` (have) |
| loudness (dB) | ✅ measured | `20·log10(rms_mean)` → dBFS (direct) |
| energy | 🔨 derived | z-blend: `rms_mean` + `onset_strength_mean` + rolloff |
| danceability | 🔨 derived | tempo-band score (~90–150 sweet spot) × pulse clarity (`onset_strength_mean/std`) × beat density |
| acousticness | 🔨 derived | high `harmonic_ratio` + low `spectral_centroid/flatness/zcr` |
| speechiness | 🔨 derived | high `zcr` + high flatness + low harmonicity |
| brightness, punch, dynamics… | 🔨 derived | our own perceptuals beyond Spotify's 13 (already banded in `taste.py`) |
| valence (“mood”) | ⚗️ experimental | mode + tempo + brightness heuristic — labeled a *proxy*, shown with a confidence caveat |
| instrumentalness | ⏭ v2 *(moved from experimental during F1)* | summary statistics can't see vocals — an honest proxy needs frame-level analysis/source separation; shipping a fake one would cost the tier system its credibility |
| time_signature | ⏭ v2 | needs a new DSP pass over audio (librosa beat/meter) → extractor addition + corpus re-run; defer |
| liveness | ❌ out | crowd-noise detection isn't honestly derivable from our features |

Each derived feature: 0–1 normalized against the cached population
(percentile-calibrated), formula recorded in the catalog. **Tiers are shown in
the UI** — honesty as a feature, exactly the project's brand.

### B2 — The analytic datasets (gold marts, Parquet + cache tables)

| Dataset | Grain | Powers |
|---|---|---|
| `feature_catalog` | one row per feature | the picker: friendly name, unit, tier (measured/derived/experimental), description, formula/provenance — extends the existing `column_descriptions` |
| `feature_stats` | feature × histogram bin + percentiles | population distribution charts without shipping raw rows |
| `track_perceptual` | bridge key | per-track derived features (cache table + Parquet mart) |
| per-user overlay | computed at request | "your tracks" markers + percentile chips |

Built by a versioned script (`scripts/build_feature_marts.py`), re-run as the
cache grows; audited by extending `warehouse-audit` (catalog/actual-column
parity — the D-4 exact-contract discipline applied to the new layer).

### B3 — The Explorer dashboard (`/explore`)

Server-rendered, D-14-compliant (form GET + SVG; HTMX only if needed):

- **Feature picker** (from the catalog, grouped by tier, with descriptions).
- **Distribution view:** population histogram + the user's tracks overlaid as
  dots + their percentile chip ("your Hexagons is louder than 91% of the
  corpus").
- **Feature × feature scatter:** pick X and Y → all cached tracks, colored by
  the existing sound clusters, user's tracks ringed (reuses the validated
  palette + map machinery from Epic C).
- **Per-window strip:** the feature's mean per time window → "your recent
  listening is 12 bpm faster."
- Deep-dive pages gain a "explore this feature" link per stat.

**Charts follow the dataviz-skill procedure again** (validated palette,
secondary encoding, tooltips).

### B4 — stretch (later): audio-analysis-style time series

Spotify's second deprecated endpoint (`get-audio-analysis`) served *within-
track* structure (beats, sections, loudness curve). Our extractor already
touches the frames — persisting a small per-track time series (RMS curve +
beat times) at extraction time would power a loudness-over-time chart on the
deep-dive page next to the spectrogram. Requires re-extraction to backfill →
schedule with B-v2 alongside time_signature.

**Acceptance (B1–B3):** a user picks any catalog feature and sees the
population distribution with their own tracks overlaid and percentile-ranked;
derived features carry visible tiers; `feature_catalog` row count == served
features (audited); marts rebuild idempotently from the cache; charts pass the
palette validator. All synthetic-tested; zero new external cost.

---

## The audit — aggro vs value

| | **A1+A2 evals + contracts** | **A3 Ollama** | **B explorer (B1–B3)** |
|---|---|---|---|
| Aggro (effort) | **Low** — 2–3 slices, no new infra | Medium — service mgmt, latency tuning | **Medium-high** — 3–4 slices (derivations, marts, dashboard) |
| Aggro (risk) | Minimal (synthetic, CI) | Model quality unknowns | Main risk = *over-claiming* derived features → mitigated by tiers + percentile calibration |
| User value | Invisible (quality guard) | $0 real LLM answers | **High — the most fun, shareable surface in the app** |
| Portfolio value | **High** (LLM evals = hiring signal) | Medium-high (local LLM ops) | **Very high** — analytics engineering + feature engineering + the "rebuilt the deprecated API" story |
| Dependency | Guards what B's grounding will touch | Independent | Builds directly on Epic A cache + Epic C clusters |
| $0 constraint | ✅ | ✅ (its whole point) | ✅ |

## Recommendation (Jordan decides)

**Epic F = Vision B (B1→B2→B3), with A1+A2 folded in as its first guard-rail
slice.** Rationale: B is the user-facing flagship and the strongest portfolio
arc; its new grounding data (percentiles, perceptual features) will flow into
`/ask`/`/classify`, which is precisely when you want A1's eval set watching.
A3 (Ollama) queues behind as its own optional epic. Rejected items stay
rejected — the KB's best contribution is knowing when *not* to reach for a
tool.

**Proposed build order:** F0 = A1+A2 (eval harness + JSON contracts) → F1
derived features + catalog → F2 stats marts + audit extension → F3 `/explore`
dashboard → F-v2 (time_signature + loudness-curve time series, needs
re-extraction).

---

# Roadmap — remaining build sequence (2026-07-09)

**Where we are:** the audio-feature engine is ~complete. Of Spotify's **13
track-level audio-features** we've rebuilt **10 reliably** — tempo, key, mode,
loudness, duration, time_signature (measured); energy, danceability,
acousticness, speechiness (derived) — plus **3 Spotify never offered**
(brightness, punch, dynamics), plus valence as a *labelled* experimental proxy,
plus the within-track **loudness curve** (F-v2a). **Deliberately NOT faked:**
`valence` and `liveness` are learned perceptual judgments with no honest DSP
version (keep valence as a labelled proxy; skip liveness). **`instrumentalness`
is REMOVED from the roadmap** — an honest version needs source separation, and
the tier-credibility cost isn't worth it (the F1 call, reinforced by journal
#19).

## Finding — `popularity` is Deprecated, NOT removed (verified 2026-07-09)

A live check of `GET /tracks` (journal #14 ethos: verify, don't trust the doc)
shows `popularity` is still returned, labelled **Deprecated**. Our own
`.agent_prompts/01` guardrail + CLAUDE.md rule 3 + `fetchers.strip_deprecated_
fields` are **over-cautious** — they call it "removed" and strip it. Reality:
available now, may vanish later. **Decision (recommend):** capture it as
**optional context metadata** — NOT an acoustic feature (it's *fetched*, not
derived — stay honest), and **NOT an ML input** (Spotify's terms forbid
training on their content; clustering stays DSP-only). Graceful-degrade if it
disappears. When built (slice ② below), un-strip in `fetchers.py`, store an
optional column, and correct CLAUDE.md rule 3 + the guardrail doc from
"removed" → "deprecated: capture as optional context, never ML, may vanish."

## The sequence (cheap → expensive)

**① F-v2c — fade + beat-grid** *(finishes the F-v2 frame-level pass; ~½ day)*.
Reallocated from the removed instrumentalness slot. Detect fade-in/fade-out by
thresholding the RMS envelope we already store, and overlay the beat grid (we
already compute beats) on the loudness curve. Reliability 🟢 (pure signal).
Deps: F-v2a. **Accept:** song page shows fade markers + beat ticks; synthetic-
tested; no re-download.

**② P — popularity context** *(small, foundational)*. Un-strip popularity;
store an optional per-track column; surface a "your taste vs. popularity" line
on `/analytics` (skew popular or obscure?) and expose it as a filterable axis
for ④. Reliability 🟢 (fetched, honestly labelled as such). Policy:
display/analysis only, never ML. Deps: none. Unblocks ④'s `target_popularity`.
**Accept:** popularity stored when present + absent-safe; a real "N% more
obscure than the corpus" line; the three docs corrected; synthetic-tested.

**③ F-v3 — structure timeline** *(the marquee; medium)*. A section-map ribbon
under the spectrogram + loudness curve: detected sections (librosa
recurrence/Laplacian on chroma+MFCC), repeated sections colour-matched, each
with its own loudness/tempo/key. Reliability 🟢 for **boundaries + repeats** —
we do NOT label "chorus/verse" (semantic → unreliable); honest "detected
sections." Deps: F-v2a (same page). Online-first + local backfill, no
re-download. **Accept:** real structure on real songs; backfill over the 117
corpus; synthetic-tested boundaries; the no-semantic-labels boundary documented.

**④ Epic G — the recommendation explorer** *(the capstone; biggest)*. Rebuild
Spotify's dead `/recommendations` as a tunable filter over OUR features: seed a
track (or set targets) → min/max/target on any perceptual feature + meter +
popularity → ranked matches from the cache (z-distance + cluster-aware).
Reliability 🟢 (filtering our own reliable features). **The biggest thesis
win** — proves the features are good enough to power reco-style retrieval. Deps:
perceptual marts ✓, clusters ✓, slice ② (for `target_popularity`). **Accept:**
a working `/recommend` surface with the tunables; deterministic + tested.

## After the audio work

**⑤ A3 — Ollama local LLM** *(optional epic; plan validated in §A3 above)*: $0
real LLM answers for `/ask` + `/classify` on the RTX 4070 Ti, guarded by the F0
golden evals (currently those surfaces run the deterministic fallback — no key).

**⑥ Polish:** DMARC `p=none` → `quarantine` → `reject` once reports are clean;
surface the loudness curve on `/analytics` too.

**Recommended order:** ① + ② as a quick foundational batch → ③ F-v3 (marquee) →
④ G (capstone) → ⑤ A3 → ⑥ polish. Reorder by appetite — ③ is independent of
① ②, so it can jump the queue if you want the visual payoff first. Every slice
holds the ground rules: bridge key, Parquet marts, synthetic tests, $0,
online-first + local backfill (no re-download).

---

# Vision C — the public era (specced 2026-07-11, owner's idea list)

**Context:** roadmap ①–⑥ is COMPLETE and live. The owner brought a 12-idea list
(public access, playlists, MPD, agentic chat, publication…); this section is
the audited spec + sequence. Two ideas were *already built* and become
enrich-not-build: ingestion progress UX (`GET /status` + dashboard poller with
bar/ETA/current-song, 2026-07-09) and the A3 local LLM (gemma4 live). Standing
constraint from 2026-07-11: **REAL data only** — no synthetic rows anywhere the
product measures or reports (SCALING.md decision note).

## Decisions (continue APP_SPEC numbering)

- **D-18 (owner, 2026-07-11): the corpus goes PUBLIC.** All corpus-level
  surfaces render without login: `/explore`, `/song/{id}` (incl. spectrogram,
  loudness curve, sections), `/recommend`, a new `/songs` catalog. Personal
  surfaces stay auth-gated (dashboard, /analytics personal overlays, archetype,
  /ask, /classify, /status). This **deliberately reverses** the 2026-07-09
  `/spectrogram` auth-gate: that gate closed an *enumeration oracle* on a
  private surface; a public catalog makes enumeration a feature. The corpus is
  the owner's own listening data, exposed by his explicit choice.
- **D-19 (owner): MPD is PARKED** — revisit after H/I/K ship. When un-parked,
  Epic J's shape is metadata-first (co-occurrence, embeddings, dbt-style
  modeling — see the saved references in §Epic J), **never** bulk audio
  acquisition. MPD is real data, so it is the legitimate future trigger for
  un-parking Spark (SCALING.md).
- **D-20 (owner): git history gets SCRUBBED (`git filter-repo`)** before the
  public flip — the dead rotated secret (2026-07-03) comes out of history.
  Cost accepted: commit hashes change; docs note the scrub date.
- **D-21: `llm_knowledge_base/` is EXCLUDED from the public repo** (synced
  course material — not ours to republish; provenance doc already says the
  canonical lives elsewhere). Replace with a pointer README at flip time.
- **D-22: audio acquisition stays yt-dlp, hardened — no source switch.**
  Residential IP + politeness limits + transient audio (D-15) + features-only
  retention is the defensible posture, bounded to tracks users actually bring.
  The quality work is **match hardening** (duration check vs Spotify
  `duration_ms`, official-audio preference, logged match confidence) — the real
  risk is wrong-version matches (live cuts, covers), not the source. Audited
  alternatives: iTunes 30s previews REJECTED (30s features are not comparable
  to full-track features — sections/arc/fades all break; a provenance-tier
  honesty problem); paid audio fails $0; user uploads legal but niche.

## Epic H — Public showcase mode ⭐ (build first)

The highest-leverage share-readiness item: converts the app from "5-seat gated
demo" into a public interactive showcase. The 5-seat Spotify allowlist keeps
gating only *personalization*.

- **H0 — guest rendering core.** Corpus routes stop redirecting anonymous
  visitors; view logic already takes population + optional user rows, so guests
  pass `user_rows=None` (no personal chips/dots/seeds). Auth-gate list stays
  explicit + tested.
- **H1 — `/songs` catalog.** Every cached track: name, artist, **popularity**,
  key features; server-side sort/filter (form-GET, no-JS house style); links to
  deep-dives. Authed extra: a "mine" filter (your ingested songs — the owner's
  "all your songs we've engineered" ask).
- **H2 — guest deep-dives + recommend.** `/song/{id}` and `/recommend` public
  (spectrogram gate reversal per D-18; seeds are corpus tracks so seeding works
  for guests too).
- **H3 — popularity on hover** (owner ask): `track_summary` + list-hover
  templates carry popularity.
- **H4 — UI cut-off sweep** (owner ask: "fields getting cut off"): Browser-pane
  audit at 375/768/1280px, fix every truncation found; live browser validation
  is the acceptance.
- **H5 — $0 always-up fallback.** A Cloudflare Worker on the zone catches
  origin-down (app off, on-demand) and serves a static "this demo runs
  on-demand — here's the case study + contact" page instead of a bare 502.
  Respects the on-demand decision; the shared link is never dead.
- **H6 — landing copy.** Explain the split: browse the corpus freely; login
  (pilot, 5 seats) personalizes.
- **H7 — guest demo persona (D-30, PULLED to Phase 1).** "View as guest" button
  → read-only session pre-loaded with the owner's taste snapshot
  (`snapshot_demo_profile.py`) → the full personalized experience without login.
  Read-only guard (no enqueue/downloads/Spotify calls); demo banner. The
  interview showpiece.

**Accept:** a logged-out browser can explore catalog → deep-dive → recommend on
the live domain; personal routes still redirect; guest paths tested; H5 page
renders when the app is stopped; all-green audits.

## Epic L — Publication (lite early, flip last)

- **L-lite (right after H):** dead-file sweep (verified-unused only) ·
  `docs/CASE_STUDY.md` — what we built, architecture, DSP/eval/RAG/local-LLM
  techniques, **and the Claude-harness methodology** (skills, memory,
  journals — the differentiating meta-story) · README rewritten for a public
  audience · how-to/quickstart guide.
- **L-flip (last):** gitleaks scan → KB extraction (D-21) → LICENSE (owner
  picks; MIT recommended for code) → `git filter-repo` scrub (D-20, fresh
  mirror clone, force-push, note the date) → flip public → verify clone+run
  from a clean machine POV.

## Epic I — Your library: playlists

New Spotify scopes (`playlist-read-private`, `playlist-read-collaborative`) →
re-consent; fetch playlists + tracks paginated; **per-user caps are
load-bearing** (a 2,000-track playlist at ~50 s/track is days on one worker):
default cap (e.g. 10 playlists / 500 tracks, config), **explicit per-playlist
"analyze this" button** (no auto-enqueue-everything), `/playlists` page showing
per-playlist coverage ("12/40 engineered"), `/status` enriched with a per-song
queue list + playlist attribution + "come back in ~X min" copy (the rest of the
owner's UX ask). Queue fairness noted: FIFO with caps first; revisit if
multi-user contention is real.

## Epic K — Talk to your library (evals first, journal #25)

**SUPERSEDED by the K0 plan — see §"Phase 4 — Epic K formal" (D-42…D-46),
the authoritative phasing (K1 chat → K2 tool-use → K3 bucketing → K4 upload →
K5/K6 gated docs).** This early sketch kept for the record; its honest-risk
note (gemma4 tool-calling may under-perform → hosted fallback optional)
carried into D-44.

## Epic J — MPD (PARKED, D-19) — the saved future plan

When revisited: **J0** license + download (~5.4 GB, AIcrowd; NEVER committed —
research-only license, `data/` gitignored) + a **systematic periodic intake
script** (owner ask: stage → validate → merge new data on demand) · **J1**
co-occurrence mart + track2vec playlist-context embeddings (real ML, zero
audio) · **J2** hybrid recommender (acoustic × co-occurrence) · **J3** Spark
un-parks on 1M real playlists. **Owner's saved references (emulate/bring in
at future date):**

- https://medium.com/inthepipeline/from-zero-to-dbt-how-to-analyze-and-build-data-models-from-spotifys-million-playlist-data-241c3d8c9b5d
- https://medium.com/inthepipeline/from-zero-to-dbt-part-2-modeling-spotifys-million-playlist-dataset-e62e350d9945
- https://docs.reccehq.com/ (dbt PR data-diff review)
- https://www.kaggle.com/datasets/himanshuwagh/spotify-million (mirror)

The dbt direction (modeling MPD in dbt + Recce for data-diff review) is noted
as the likely future transform framework evaluation when J un-parks — strongly
portfolio-relevant.

## Epic M — Tester lifecycle & notifications (PARKED 2026-07-11)

> **PARKED by owner the same day it was specced** — revisit ONLY if we get
> *materially* more users AND a paid email/Exchange account. Rationale: the
> value (auto-email "your analysis is ready") scales with user count, but the
> Spotify dev-mode **5-seat cap** blocks user growth (extended quota needs a
> registered business ≥250K MAU — off the table), so M would be a notification
> system for an audience that can't grow. The manual runbook (owner runs
> `train_clusters.py` + texts the tester) fully covers ≤5 testers. Spec kept
> below for when the triggers flip. **The one durable takeaway:** M3's email
> dependency (Brevo + DKIM, D-23) is recorded so a future build starts there.

Automate the good-tester-experience runbook: on login detect new songs + show
ETA (mostly EXISTS), auto-retrain when a batch finishes, and email the tester
"your analysis is ready." **Audit finding — this is three very different costs,
and "another worker per login" is NOT the shape:** detection is already
login-triggered and one FIFO worker already has a post-drain hook. Build the
delta, extend the one worker — don't spawn more (journal #23 lock).

**Decisions:**
- **D-23: outbound email = a transactional relay (Brevo free 300/day) + domain
  DKIM in Cloudflare.** REQUIRED because DMARC is now `p=quarantine` — an
  un-aligned send spams the tester. The relay API key lives in the gitignored
  `.env` (this is NOT a Spotify secret — the PKCE-no-secret ground rule is
  about Spotify auth and is unaffected). **M3 depends on the send-as-the-domain
  setup** (`vercilloanalytics-domain-setup` memory) being done first.
- **D-24: add the `user-read-email` scope → testers RE-CONSENT.** Store an
  email ONLY with an explicit opt-in ("email me when my analysis is ready"
  checkbox); one email per batch; a `notifications` table for idempotency
  (never double-send). /privacy updated. CASL-clean (owner is in Canada).
- **D-25: one worker, more hooks — not many.** Per-user batch completion is
  tracked via a session→track-set record; the existing single-instance worker
  drains and, on settle-to-zero-for-that-set, runs retrain + sends pending
  notifications. Failure-safe: an email or retrain error logs+continues, never
  crashes the drain (the journal-#22 poll-loop guard pattern).

**Slices (cheap → expensive):**
- **M1 — copy only, no email:** dashboard/`/status` says "X new songs detected ·
  ~Y min left" (enhances the existing poller). Trivial.
- **M2 — auto-retrain, no email:** extend the worker post-drain hook to retrain
  clusters when new tracks landed (debounced to queue-settle, idempotent model
  versioning, guarded). Removes the manual `train_clusters.py` step. Touches the
  worker → do it when NOT mid-trial.
- **M3 — the notification subsystem:** Brevo+DKIM (owner DNS, D-23) · new scope +
  consent checkbox + email storage (D-24) · per-user batch tracking + a
  `notifications` table (D-25) · an "analysis ready" template · failure-safe
  send · tests against a MOCK relay (synthetic — code-correctness, never a real
  send in CI). Evals/tests are the acceptance; a real send to the owner's own
  address is the live proof.

**Sequence:** slot AFTER Epic H (public showcase is the sharing priority). M1 can
land anytime (trivial copy). M2 is cheap but worker-touching — between trials.
M3 waits on the outbound-email groundwork. **For the CURRENT trial: the manual
runbook stands — do NOT hot-patch a live drain.**

## Pilot trial — T0 OPENS NOW (2026-07-11, owner decision)

**2/5 Spotify dev-mode seats are filled** (the first pilot user added 07-09, the second 07-10)
and the trial starts **immediately — first coordinated window the weekend of
2026-07-11/12**, deliberately BEFORE Epic H: real tester feedback steers H's
copy/polish, and the pilot flow is already proven live (52 s queued→done,
2026-07-09). The experience is gated on ONE thing: the app must be RUNNING
(on-demand hosting — a dark app 502s the whole domain).

**Per-tester window protocol (owner runbook):**
1. `start_app.bat` → confirm green (`status_app.bat` / app-verify).
2. Invite the tester NOW: "log in, watch it start, come back in ~an hour."
3. What they get: instant top-tracks dashboard (metadata + any cache overlap);
   everything else auto-queues at ~50 s/track with the live progress bar/ETA —
   **durable queue**, so leaving and returning later is the designed path;
   typical library ≈ 1–1.5 h to full coverage; later visits instant.
4. Stagger testers when possible (single FIFO worker: two ~100-track libraries
   at once ≈ ~3 h combined; ETA stays honest either way).
5. After their drain: `uv run python scripts/train_clusters.py` once — new
   tracks reach analytics instantly via online assignment, but only a retrain
   places them as dots on the acoustic map.
6. `stop_app.bat` to close the window (auto cache backup — their extraction
   hours are the asset, D-17).

**Expectation to set with testers:** analysis covers their TOP tracks (3 time
ranges) — playlists arrive with Epic I; a few obscure tracks may honestly fail
matching (dead-letter, count shown). Collect their confusions verbatim — that
list becomes H4/H6 input.

## The sequence (owner-approved 2026-07-11)

**H (public showcase) → L-lite (case study + README) → I (playlists) → K
(agentic chat) → L-flip (scrub + public GitHub)** · J parked · **M parked**
(revisit only with materially more users + paid email) · **pilot trial runs
throughout, starting T0 = 2026-07-11/12.** Every slice holds
the ground rules: bridge key, Parquet, PKCE-no-secret, synthetic tests
(code-correctness only — product data stays REAL), $0, evals before LLM
surfaces, live browser validation to close every build.

---

# Vision D — feature roadmap batch 2 (owner list 2026-07-11, post-pilot)

The owner's 16-item list, audited. **Most of it is already specced** — this
section adds the genuinely new work (2 epics + 1 bug), reshapes MPD/Spark from
PARKED to ACTIVE (as **metadata-only**, un-parking Spark), and sets an
interleaved sequence.

## Where each of the 16 items lives

| # | Item | Home | Status |
|---|---|---|---|
| 1 | Filter all songs vs your features / public access | **Epic H** | specced |
| 2 | Brainstorm reliable audio source | **D-22 + Epic O** | decided: harden yt-dlp, no source switch |
| 3 | What are all the taste archetypes | **Epic N** (new) | NEW |
| 4 | Popularity on hover | **H3** | specced (Phase 1) |
| 5 | All songs with audio features | **H1** (`/songs`) | specced |
| 6 | All your engineered/ingested songs | **H1** "mine" filter | specced |
| 7 | Playlists + ingested/engineered status | **Epic I** | specced |
| 8 | MPD for constant training data | **Epic J** (reshaped) | metadata-only, un-parked |
| 9 | Ollama talk-to-songs + bucketing | **Epic K** | specced |
| 10 | Ingestion progress / when to come back | **exists** (`/status`) + Epic I | enrich |
| 11 | UI polish, fields cut off | **H4** | specced (Phase 1) |
| 12 | Cleanup + how-to + portfolio case study | **Epic L-lite** | specced |
| 13 | Push to public GitHub | **Epic L-flip** | specced |
| 14 | Explain σ-shift / std dev to users | **Epic N** (new) | NEW |
| 15 | Remove duplicate songs + methodology | **Epic O** (new) | NEW |
| 16 | Recommend-seed targets don't update on new seed | **Bug B1** (new) | NEW |

## Decisions (continue numbering)

- **D-26: MPD is METADATA-ONLY (owner, 2026-07-11) — affirms D-19, does NOT
  reverse it.** No YouTube audio acquisition off MPD, ever. MPD gives real
  *behavioral* signal (playlist co-occurrence, embeddings); our *acoustic*
  features stay bounded to user-brought tracks (159+). Honest limitation
  documented in the UI: hybrid acoustic×co-occurrence reco is strongest on the
  **overlap** (MPD tracks we also have audio for); pure co-occurrence spans all
  MPD tracks, pure acoustic spans ours.
- **D-27: Spark UN-PARKS for the MPD metadata layer — the real-data trigger has
  fired.** Spark is the right tool for 66M playlist-track rows (co-occurrence,
  track2vec, dedup, aggregation). It is the **WRONG** tool for audio extraction
  (I/O-bound download = the existing queue+workers); **Spark never touches the
  download path.** This split IS the portfolio point (right tool per stage).
  No synthetic volume — Spark runs on REAL 66M MPD rows (honors the real-data
  vision; [[real-data-only-no-synthetic-benchmarks]]).
- **D-28: dedup is a FLAG + an acquisition guard, never a second ID.** Ground
  rule #1 holds — `spotify_track_id` stays THE bridge key. Dedup detects
  near-duplicates (same name+artist+~duration, or audio-feature near-identity)
  and (a) flags them for display/analysis, (b) skips re-downloading audio for a
  track whose twin is already cached (efficiency), (c) adds a warehouse-audit
  `DUPLICATE_TRACKS` check. It does NOT mint a canonical-id join key.
- **D-29: sequence = INTERLEAVE (owner):** Phase 1 bugs + quick wins → Phase 2
  MPD/Spark (data-platform depth) → Phase 3 public showcase + GitHub publish.
- **D-30: guest demo persona (owner, 2026-07-11) — the interview showpiece.** A
  "View as guest" button loads a READ-ONLY session pre-populated with the
  OWNER's taste snapshot, so anyone (interviewer) sees the FULL personalized
  experience — dashboard, archetype, drift, acoustic map — with no login and no
  5-seat gate. Snapshot captured by `scripts/snapshot_demo_profile.py` (owner
  runs it while logged in — his `range_ids` + top artists → a stored demo
  profile; refreshable), so guests need no live Spotify token (his tracks are
  cached). Guest session is strictly read-only: no enqueue, no downloads, no
  Spotify calls; a banner reads "Demo view — Jordan's account; log in for your
  own." Intentionally exposes the owner's personal profile publicly (his
  explicit ask, consistent with D-18). Depends on H0 (guest rendering core) →
  pulls a slice of Epic H forward into Phase 1.
- **D-31: drop the "Taste Pilot" sub-label (owner) — top-left = "Vercillo
  Analytics" only.** The owner read the intentional "taste/test pilot" pun as a
  typo; a *perceived* typo hurts a portfolio more than a lost pun helps, and the
  bare brand is cleanest for an interview audience. Trivial Phase 1 edit (nav +
  `<title>` templates).

## Epic N — Explainability & legibility (NEW, Phase 1)

Make the analytics legible to non-experts — a genuine product/DS-communication
portfolio signal.
- **N1 — stats explainer** (item 14): plain-language glossary + inline "how to
  read this" for **σ / standard deviation / RMS σ-shift / percentile** wherever
  they appear (/analytics signature, drift, /explore chips). E.g. "σ = standard
  deviation — how far from typical; ±1σ ≈ more unusual than ~68% of tracks."
  Deterministic, no LLM. Tooltips + one expandable methodology note.
- **N2 — archetype taxonomy** (item 3): a page/section listing all **12
  archetypes** — "The {motion} {breadth}", motion ∈ {Anchored, Drifting,
  Roaming, Shape-shifting} (D-9 σ-bands) × breadth ∈ {Loyalist, Dualist,
  Eclectic} — each with its plain-language definition + the threshold that
  earns it, and "you are here" highlighted for the logged-in user. Reads
  straight from `archetype.py` (single source of truth — no drift).

**Accept:** every σ/percentile on the site has a hover/why; the 12-archetype
map renders with the user's cell marked; deterministic + tested.

## Epic O — Dedup & acquisition quality (NEW, Phase 1)

Items 2 + 15 — data-quality that becomes load-bearing before any scale work.
- **O1 — dedup** (D-28): a near-duplicate detector (name+artist normalized +
  duration window, with audio-feature cosine as a tiebreak when both are
  cached) → a `duplicate_of` FLAG (display/analysis only, NOT a join key) +
  intake guard (don't re-download a twin) + warehouse-audit `DUPLICATE_TRACKS`.
- **O2 — acquisition-match hardening** (D-22, brainstorm result): the audio
  brainstorm's honest answer is *harden matching, don't switch source* —
  duration check vs Spotify `duration_ms`, official-audio preference, logged
  **match confidence**; the real risk is wrong-version matches (live/cover),
  not yt-dlp itself. 30s previews stay REJECTED (feature-comparability). This
  matters more as the corpus grows via real users.

**Accept:** the DUPLICATE_TRACKS audit flags known dupes; a re-ingest of a twin
is skipped with a logged reason; match-confidence is recorded per extraction.

### O1 — READY-TO-EXECUTE plan (data-platform-expert, 2026-07-12)

Consulted + validated on the real corpus during the 2026-07-12 orchestrated
session; **prototyped detector found 10 genuine dupe clusters** in `dim_tracks`
(Muse pairs, Linkin Park "In the End" 216800 vs 216880 ms, Green Day "Holiday")
— so `DUPLICATE_TRACKS` will read **true** on today's corpus, correctly (advisory
WARNING, 0 errors; same severity class as AUDIO_ORPHANS). Deferred from the
2026-07-12 session (large slice, budget) — execute as ONE focused pass.

- **NEW `src/store/dedup.py`** — pure, **stdlib-only** (so the uv-isolated audit
  can `exec_module` it): `normalize_title` (strip remaster/live/feat/parenthetical/
  diacritics via a " - "/"(...)" gate — only qualifiers, never plain words),
  `normalize_artist` (conservative — no multi-artist split), `DedupRecord`/
  `DuplicateCluster` dataclasses, `find_duplicate_clusters` (bucket by
  (title,artist) → union-find within a duration window; cosine as a **reject-only**
  tiebreak when both cached), `duplicate_of_map`. **Precision-biased** (a false
  positive wrongly skips a real download). Constants `DEFAULT_DURATION_WINDOW_MS=7000`,
  `DEFAULT_COSINE_MIN=0.95` — corpus-tunable (journal #19/#24).
- **`models.py`** — 2 nullable cols on `TrackMeta`: `duration_ms` (fetched
  context, dedup window) + `duplicate_of` (**soft ref to a spotify_track_id —
  NOT a PK/FK, nothing joins on it**; D-28 / ground rule #1).
- **`cache.py`** — `_ADDED_COLUMNS["track_meta"]` += both (forward-only migration
  #journal-18); `remember_meta` threads `duration_ms` preserve-if-absent (like
  popularity, never touches `duplicate_of`); methods `find_cached_twin`,
  `resolve_duplicate`/`_resolve_as_duplicate` (flag + job done, NO re-download),
  `_guard_cached_twins`, `duplicate_flags`, `refresh_duplicate_flags` (cosine
  refines the display flag where both cached), `_dedup_vectors` (z-scored like
  `similar()`). **enqueue intake guard**: drop misses whose twin is already
  cached, before the (unchanged) queue loop.
- **`extractor.py`** — post-claim guard in `extract_one`: `find_cached_twin` →
  `resolve_duplicate` + return (catches the both-new race; best-effort, never raises).
- **audit** `check_duplicates` (importlib-load dedup.py by path, mirrors
  `check_marts`) → `DUPLICATE_TRACKS` flag over `dim_tracks`; wire into `main()`.
- **NEW `scripts/refresh_dedup.py`** (mirror the backfills) + worker post-drain
  hook (`cache.refresh_duplicate_flags()` next to `rebuild_marts`).
- **Feeders (cross-domain, small):** `app.py` `meta_items` += `duration_ms`
  (`fetch_top_tracks` returns it); `seed_cache.py` same; dashboard "N of M
  analyzed" resolves a guarded twin through its canonical (~6 lines, cosmetic).
- **Tests (~10–12, synthetic):** `test_dedup.py` (normalization, clustering
  window/artist gates, canonical preference, cosine reject) + `test_store.py`
  (enqueue guard idempotent + bridge-key-untouched, extract-time race, no-false-
  guard, refresh self-heal) + an audit test.
- **Invariant self-audit (expert-confirmed):** bridge key SAFE (soft ref, no
  join); idempotency SAFE (guard before queue loop, done never re-selected);
  stranding SELF-HEALING (twin re-queues if canonical ever vanishes); pre-download
  guards are **metadata-only by necessity** (can't hear a track before downloading
  it) — cosine only refines the display flag. **Pruning dupes is a separate,
  IRREVERSIBLE owner call (D-28 = flag-not-delete) — escalate, never auto-delete.**

## Epic J — MPD (RESHAPED: metadata-only, ACTIVE, Phase 2)

Un-parked as metadata-only (D-26) + Spark un-park (D-27). The owner's
"systematic local script" = an MPD **metadata** ETL driver (no audio).
- **J0 — intake:** license + download (~5.4 GB, AIcrowd; NEVER committed —
  research license, `data/` gitignored) + `scripts/mpd_intake.py` (owner runs
  locally; stages an MPD slice → validate → merge, repeatable + idempotent).
- **J1 — Spark metadata ETL:** playlists / tracks / playlist_tracks staged
  (~66M rows) → **dedup (Epic O)** → **co-occurrence mart** (track-track
  co-occurrence counts) + **track2vec** (playlists as sequences → skip-gram →
  track embeddings). Parquet, hash-bucket partitioned on the bridge key.
- **J2 — hybrid recommender:** acoustic (our z-distance) × co-occurrence (MPD
  embeddings) combined on the overlap; graceful degradation to whichever
  single signal a track has (D-26 honesty).
- **J3 — Spark-at-scale proof:** run J1 on the REAL 66M rows in Spark local
  mode (partitioned slices if RAM-bound), benchmark throughput + the
  partitioning story → the honest "at scale on real data" artifact SCALING.md
  promised. No synthetic rows.
- The saved dbt/Recce references (§Epic J parked block above) inform J1's
  modeling; evaluating dbt as the transform framework is a J-stretch.

**Accept:** `mpd_intake.py` loads a slice end-to-end; co-occurrence + embeddings
marts build via Spark on real rows; hybrid reco returns sensible neighbors on
the overlap; parity/quality tested on a small REAL fixture slice (never
synthetic); benchmark documented.

## Bug B1 — recommend-seed targets don't refresh (Phase 1)

Item 16: in `/recommend` seed mode, selecting a NEW seed song doesn't update the
min/target/max tunables (they keep the previous fill or stay blank). Repro +
root-cause first (likely: the target inputs retain prior submitted values over
the new seed's server-side fill, or the seed change doesn't re-trigger
`seed_targets`). Fix so a new seed re-derives + repopulates every visible target;
regression test on the seed→targets mapping.

## Sequence — Vision D (owner-approved interleave, D-29)

- **Phase 1 — bugs + quick wins** (fast, mostly frontend, high-value):
  **D-31 rename** (drop "Taste Pilot" → "Vercillo Analytics", trivial) ·
  **B1** (seed bug) · **H3** (popularity hover) · **H4** (UI cut-off sweep) ·
  **N1** (stats explainer) · **N2** (archetype taxonomy) · **O1** (dedup) ·
  **H0 + H7 guest demo persona** (D-30 — the interview showpiece: guest
  rendering core + owner-data snapshot + "View as guest" button; pulled forward
  from Epic H because its interview value is highest-leverage now).
- **Phase 2 — MPD + Spark** (data-platform depth): **J0 → J1 → J2 → J3** +
  **O2** (match hardening folds in as the corpus grows).
- **Phase 3 — share + publish** (last): **H0/H1/H2/H5/H6** (full public
  showcase) · **Epic I** (playlists — pairs here, needs re-consent) ·
  **Epic K** (agentic chat/bucketing — benefits from the richer post-MPD data) ·
  **L-lite → L-flip** (case study, then public GitHub).

Same ground rules throughout: bridge key, Parquet, PKCE-no-secret, REAL data
only (synthetic = test fixtures for code-correctness only), $0, evals before LLM
surfaces, live browser validation to close every build.

---

# Vision E — the product era (Phases 3–6, specced 2026-07-14)

**Context:** Vision D Phase 1 is 8/8 COMPLETE. The owner re-scoped the arc in an
orchestrated design session (consults: `webapp-expert` IA plan + the
`research-expert`'s first outing → [`docs/SPOTIFY_API_RESEARCH.md`](SPOTIFY_API_RESEARCH.md);
four owner forks answered). **The mission, in the owner's words:** this website
is step one toward a **robust, free, legally-obtained audio-feature dataset
replacing the deprecated Spotify API**, enabling more complicated ML later. The
research confirmed that framing is not a stopgap — extended quota now needs a
≥250k-MAU registered business, so **local derivation is the permanent
architecture**.

**Load-bearing research finds (full brief in SPOTIFY_API_RESEARCH.md):** there
were TWO deprecation waves (Nov-2024 + Feb-2026); `GET /artists/{id}/top-tracks`
is removed with **"no replacement"**; batch gets + popularity + genres are
removed-on-paper but **still answering on our PKCE tokens** (enforcement appears
token-type-staged — borrowed time, absent-safe, never load-bearing); playlists
are **own+collaborative only**; the **5-seat cap is the platform ceiling**;
search is limited to 10; playlist items page at 50; the guardrails file needs a
second correction wave.

## Decisions (owner, 2026-07-14)

- **D-32 — roadmap re-sequenced (supersedes D-29's phase order):** Phase 3 =
  the full product surface + publication exit-gate (H remainder + I + NEW Epic P
  artists/genres + O2 + L). Phase 4 = Epic K formal (agentic chat). Phase 5 =
  MPD (Epic J shape unchanged; Spark un-parks here). Phase 6 = the ML capstone.
- **D-33 — artist top-10 doctrine:** the artist page's core is DERIVED — "**your**
  top tracks by this artist" (ranges/ranks we already store, 0 API calls,
  always renders). The live official top-10 is attempted **absent-safe, authed
  only, never load-bearing** (deprecated, no replacement; verify live at build
  per journal #20) with an honest caption when dark. Acquisition for any
  rendered artist-track list = the **analyze-on-demand button** (explicit,
  bounded — the Epic-I pattern).
- **D-34 — top-tracks fetch depth 20→50 per range** (the "why only 39 songs"
  root cause: 3×20 with overlap ≈ 39 unique). Extract a `_TOP_LIMIT` constant
  so the My-Library "why N" explainer derives from it and can't lie. New-user
  first analysis grows to ~1.5–2.5 h worst case — absorbed by the durable queue
  + O1 dedup guard; the owner's own corpus grows on his next login.
- **D-35 — nav IA (webapp-expert):** six items, two visually-grouped clusters —
  **You:** Dashboard · Analytics · Artists / **Corpus:** Library · Explore ·
  Recommend. Library holds the ONLY tabs (All songs · My songs · Playlists —
  "My Library" is a tab, not a 7th item). Genres live INSIDE Artists (the only
  place the data honestly exists). Deep-dives (`/song/{id}`, `/artist/{id}`)
  stay out of nav. **Guest lands on /dashboard** (read-only replica).
- **D-36 — artist metadata serving path:** a new **`artist_meta` cache table**
  (artist_id PK, name, genres, followers, popularity, image_url), populated
  FREE at dashboard build (we already fetch genres+images every login and drop
  them); `dim_artists` is a one-time seed, not a serving path. `artist.genres`
  is now docs-Deprecated → the stored copy is the system of record; every genre
  surface carries the coverage-honesty caption (journal #9).
- **D-37 — playlists (Epic I, research-corrected):** own + collaborative
  playlists ONLY (platform reality — design the picker around "your playlists",
  no arbitrary-URL box). Scopes += `playlist-read-private
  playlist-read-collaborative` → **all 5 seats re-consent**. Items page at 50
  (`min(limit,100)` must become 50); read `item`/`items.total` with deprecated
  fallbacks; `snapshot_id` skips unchanged playlists; explicit per-playlist
  Analyze button + config caps (default 10 playlists / 500 tracks per user);
  429 → sleep(Retry-After) in the ingest loop.
- **D-38 — the public-GitHub flip is the Phase-3 EXIT GATE** (case-study/README
  written mid-phase; flip lands after artists/library/playlists are live, so
  the repo goes public showing the full dashboard).
- **D-39 — Phase-4 scope:** K0 = an interview-style design session
  (llm-rag-expert + the KB) producing K's own phased plan. **Committed builds:**
  agentic RAG chat (gemma4, tool-use over the P5 read-only DuckDB core) +
  **multimodal upload** (user uploads their OWN audio → full DSP → their
  library — legally clean, directly serves the dataset mission). **Gated
  explorations (design-docs with explicit data-requirement go-gates):** LoRA
  adapters + RL-updated recommendations — with ≤5 users there is today no
  adapter-training corpus and no RL reward signal; the go-gate names the data
  that would unlock each.
- **D-40 — the D-18 public flip lands in TWO slices (owner via lead, 2026-07-15,
  P3.3):** the corpus context builders (`_explore_context`, `_recommend_context`)
  hard-require a user taste (`return None` without `range_ids`), so a blanket
  anon gate-drop is a real builder refactor, not a cheap flip. Split:
  **(a) shipped in P3.3** — `/library` (new, population-only by design) + `/song`
  + `/spectrogram` go public now (all three are taste-free), which already
  delivers the core D-18 value: anyone browses the catalog and opens any song's
  deep-dive with no login. **(b) deferred** — `/explore` + `/recommend` stay
  viewer-gated until a dedicated slice makes their builders render population-only
  (visitor overlay absent) + their templates handle the no-taste state. That
  slice is the true "corpus fully public" step; it precedes or accompanies the
  P3.7 exit-gate flip.

- **D-41 — playlist import caps + membership (owner, 2026-07-15, P3.4):**
  per-import cap = **100 tracks** (`config.PLAYLIST_IMPORT_CAP`, env-tunable) —
  a TOTAL, enforced by slicing `ids[:cap]` before enqueue (the fetcher `limit`
  is only a page size, so passing it doesn't bound the fetch). Analyze is
  restricted to the user's **own + collaborative** playlists (membership checked
  server-side BEFORE any fetch) — the song cache is public corpus data (D-18),
  so this bounds who can inject tracks into it + burn worker time; the cap is
  the load-bearing throughput control either way. Adding the two playlist scopes
  forces **all pilot users to re-consent** on next login (proactive
  `has_playlist_scope` check → a graceful re-consent CTA on `/playlists`, not a
  403); the scope list + privacy copy derive from one `config.SCOPES` source.

## Phase 3 — the product surface (build order)

- **P3.0 — groundwork (fetcher hardening + the 50 bump):** `_TOP_LIMIT=50` +
  explainer plumbing (D-34) · playlist fetcher fixes (50/page, `items` fallbacks,
  spotipy URL check) · search limit 10 · batch-`/artists` singles fallback
  (≥0.5 s throttle) · **guardrails-file refresh wave 2** (per the research
  brief's flagged conflicts) · capture artist `popularity` in
  `fetch_top_artists` (absent-safe).
- **P3.1 — artist_meta foundation (D-36):** table + `remember_artists()`
  (preserve-if-absent) + `all_artist_meta()` · `track_meta` += `album_image_url`
  + `primary_artist_id` (both already on fetched rows, currently dropped) ·
  one-time `seed_artist_meta.py` from `dim_artists` · dashboard build persists
  what it already fetches.
- **P3.2 — Epic P: Artists.** `/artists` (viewer): your top artists, hover card
  (overall popularity · genres · aggregate audio features across OUR analyzed
  tracks, grouped by primary artist) + ONE form-GET comparison chart (ranked
  bars per picked perceptual feature) + genre chips/filter + genre comparison
  (D-35: genres live here). `/artist/{id}` (viewer): your top-5 by this artist
  (derived core) vs the official top-10 (absent-safe live, authed, D-33) +
  **"similar in your library"** (artist_profiles acoustic centroids — the
  honest related-artists replacement: "sounds alike HERE", labelled so) +
  analyze-on-demand POST (authed, ≤10 tracks).
- **P3.3 — Epic H remainder: Library. ✅ SHIPPED (2026-07-15, 06da10d).**
  `/library` public (D-18): the H1 catalog over the full cache —
  search/sort/filter (form-GET), `duplicate_of` "same recording as" annotation,
  album art · tabs **My songs** (viewer: your analyzed ∩ catalog + the honest
  "why only N" explainer derived from `_TOP_LIMIT`) and **Playlists** (authed
  placeholder; P3.4). `/song` + `/spectrogram` flipped public alongside it.
  Per **D-40** the corpus flip is partial: `/explore` + `/recommend` stay
  viewer-gated pending a taste-optional builder refactor (deferred slice).
- **P3.4 — Epic I: playlists (D-37/D-41). ✅ SHIPPED (2026-07-15, commits
  30cb7b9/cccad88, 401 tests, deployed ALL-FALSE; authed live-path pending
  owner re-login).** Re-consent landed FIRST (P3.4a: playlist scopes +
  `has_playlist_scope` + privacy disclosure, single-sourced). `/playlists`
  (authed): re-consent CTA vs own+collaborative card list. `POST
  /playlists/{id}/analyze`: scope+membership gated → server-side re-fetch →
  cap-as-total slice → remember_meta → enqueue (O1 guard); coverage reported via
  a session flash (not a query param — XSS-safe). **Deferred (own slice):**
  per-playlist coverage on the LIST ("12/40") needs a playlist→ids membership
  table (not cache-cheap today) — shown at Analyze time instead; and `/status`
  playlist attribution (must NOT reuse `range_ids`, which drives taste analytics).
- **P3.5 — guest dashboard replica (owner ask). ✅ SHIPPED (2026-07-16,
  commit 3158f49, 409 tests, deployed ALL-FALSE, guest path browser-validated
  live on real data — 117/117 coverage, drift 0.141σ, artist genres joined).**
  Built as specced EXCEPT one deliberate deviation (journal #27,
  derive-don't-transcribe): the snapshot schema is UNCHANGED — display data is
  derived at render (`library_rows` for name/art/popularity, `all_artist_meta`
  for genres/images, features for ✓/hover), so no re-snapshot ordering
  dependency exists and the snapshot can never go stale against the cache.
  `guest_dashboard_context()` (zero API calls — tests rig fetchers to explode) ·
  `/dashboard` branches authed→live / guest→replica / else→/ · `/guest` lands
  on /dashboard · ask-form authed-gated · nav shows Dashboard to guests.
- **P3.6 — H5 + H6 + O2. ✅ SHIPPED (2026-07-16, commits 0562601/486384f/
  22f87e9, 417 tests, deployed ALL-FALSE; H5 Worker deploy = owner's 2-min
  dashboard step, doc'd in SELF_HOSTING §6a).** O2: `resolve_youtube_match`
  scores ytsearch5 candidates by title keywords + duration-vs-`duration_ms`
  bands (pure, offline-tested), logs every decision, records
  `match_confidence` per extraction (`_ADDED_COLUMNS` FLOAT, preserved on
  rewrites). **Heuristic-v1 weights are selection+recording ONLY — no hard
  rejection; the rejection threshold awaits corpus evidence (owner/Fable
  signs).** H6: the landing explains the three access tiers (browse freely /
  demo / login, demo tier honestly disappears without a snapshot). H5:
  `infra/cloudflare/origin-fallback-worker.js` — origin-down family
  (502/504/521-523/530) → an honest 503 "runs on-demand" card; healthy origin
  passes through untouched; /healthz + non-GET keep machine-readable truth.
- **P3.7 — Epic L lite → flip (D-38, the exit gate). ✅ READY TO FLIP
  (2026-07-16, Fable session 39): every item done except the flip itself —
  the owner's hand.** Dead-file sweep (PR_REFERENCE→legacy, role
  prompt→.agent_prompts) · `docs/CASE_STUDY.md` · README product-era pass +
  run-it-yourself · MIT LICENSE · gitleaks 8.24.3 over ALL history (3 findings
  = the one rotated-dead secret) · agile-coach pre-flip review (caught 3
  blockers: employer email in commit metadata → mailmapped to live.com; a 2nd
  pilot name → genericized; missing KB .gitignore → added) · `git filter-repo`
  ×2 (replace-text: dead secret + both pilot names · mailmap · KB removed from
  all history D-21 · ALL `__pycache__`/.pyc stripped — the secret survived
  inside committed BYTECODE from the original upload; caught by the
  post-rewrite verification sweep, journal #32) · force-pushed · re-verified
  clean (gitleaks "no leaks found"; full-value/name/email/KB/pyc greps all
  zero) · 417 tests green · CI green on the rewritten history (after fixing a
  test-only cookie-jar ordering flake) · app-verify ALL-FALSE. **Remaining:
  GitHub Settings → Danger Zone → Change visibility → Public (owner). Phase 3
  EXITS when the flip lands.**

**Phase-3 accept:** all six nav surfaces live + browser-validated at
375/768/1280 (anon, guest, authed × the gate matrix); playlist ingest proven on
a real playlist end-to-end; guest dashboard renders the replica with art; the
repo is PUBLIC with the case study. Tests green (CI-equiv) + both audits at
every slice; every genre/borrowed-time surface carries its honesty caption.

## Phase 4 — Epic K formal: "Talk to your data" (the owner's reset, 2026-07-17)

**✅ K0 DESIGN SESSION DONE (2026-07-16, session 41) → ✅ RESET + DEEPENED
(2026-07-17, session 42, Fable + data-platform + the NEW chat-analyst-expert;
decisions D-42…D-50).** The owner's product frame: **an on-demand data
analyst for your music** — it develops a grounded STORY from your analyzed
songs and answers AD-HOC questions; **gemma4:12b local ONLY** (the
deterministic fallback stays the D-5 safety net; gates decide SCOPE, never
provider); **every prompt+response logged** into a review-session flywheel
(the logs are the dataset that eventually un-gates K5); **RTCROS** is the
prompt contract; and a **data-first SEMANTIC LAYER** precedes any chat.
K0's original exit items stand (the `force_fallback` fix; the first dated
gemma4 baseline — softer than committed: 2 of its classify "LLM" grades were
actually fallback output after cold-load timeouts; re-baseline with per-case
sources before any D-48 delta claim).

**The load-bearing probe finding (2026-07-17, data-platform, VERIFIED-live):
the corpus is now 796 analyzed tracks** (6.8× since the public flip — real
playlist imports) **and the planes have diverged**: the star-schema gold that
`warehouse_agent` reads is frozen at Jul-4 (118 tracks) while cache+marts are
live at 796. Un-fixed, the chat contradicts itself ("796 analyzed" in the
story, "118" from ad-hoc SQL). Also: clusters cover only 39% (trained Jul-11
on 311), and 2 broken extractions (tempo 0 / −180 dBFS) would poison
superlatives. **Hence K0.5 below — the data floor ships before any chat.**

- **D-42 — the eval-first spine + gate thresholds (owner):** every K slice
  builds its golden set BEFORE its feature (journal #25). **SAFETY checks
  gate at 100%** (`no_invention`, the injection set, `canonical_name_preserved`
  — one failure = no ship, never averaged away); **QUALITY checks gate at 80%**
  (`must_cite`, `context_carry`, tool selection). Each new set is versioned
  (`_v1`), grown-not-overwritten, graded deterministically, and reported
  disaggregated beside the constant baseline AND the deterministic fallback
  (the honesty anchors: fallback 15/15, constant 0/15 on the existing set).
- **D-43 — K1 `/chat` access (owner): viewer-gated + capped.** Authed + guest
  sessions only (the /explore gate), ~20 turns/session, server-side history
  `{taste_snapshot frozen at session start, turns[]}`. Ctx budget (8192):
  system+contract ~350 · grounding ~2K recomputed once per session · rolling
  history ~4K, drop-oldest verbatim (NO summarization — a second LLM call
  that can hallucinate) · output 1024. Marts stay OUT of K1 (the pre-composed
  taste object is the higher-precision path); marts enter only via K2 tools.
  Per-turn fallback exactly as today: a degraded turn answers from the pinned
  taste object (D-5), stateless by design. **Build order: the cheap probe
  FIRST** — script the chat golden cases as raw calls against live gemma4 and
  read ~20 turns before building any session machinery; if 12B can't carry
  4 turns, **cap at 2-3 (RESET 2026-07-17: gemma4-only — no hosted routing;
  gates decide scope, never provider).** Chat has TWO modes over one budget:
  **STORY** (develop the listener's data story — ≤3 sections, its own golden
  cases before the feature) and **ADHOC** (answer the question from context).
- **D-44 — K2 tool-use SHIPS, gated (owner — the expert recommended deferring;
  owner chose ship):** gates = K1's GO passed AND the injection set at 100%.
  The expert's "per-user warehouse isolation" blocker DISSOLVES under D-18 —
  the gold warehouse is the owner's own deliberately-public corpus (the same
  data /library serves anonymously); session taste never enters the sandbox.
  Design: gemma4 has NO native tool API → JSON-action loop in the existing
  `format=json` envelope (`{thoughts, action:{tool,args}} | {thoughts, answer,
  cited}`), reusing `_parse_llm_json`; **depth cap 3** (schema → query →
  answer; on cap-exceed degrade to the K1 grounded fallback); tools = the P5
  trio as-is behind `is_safe_sql` + the locked sandbox (D-10), except a
  **chat-specific max_rows≈20** re-injected as a compact rendered table (the
  MCP path keeps 200). The injection eval set covers three attack classes:
  prompt-injection via track/artist names in the grounding (untrusted library
  strings — the case exists TODAY at `_grounding_text`), SQL injection via
  chat (proves `is_safe_sql` + readable rejection), and tool-arg manipulation
  (max_rows clamp, file-function `_FORBIDDEN`, sandbox backstop) — plus a
  guard-bypassed control run to prove the eval distinguishes guarded from
  unguarded. **RESET 2026-07-17: the hosted escape hatch is DEAD (gemma4-only,
  owner) — if gemma4 can't clear the tool bar, K2's gate stays closed and chat
  ships story+adhoc-grounded only; the flywheel + future adapters are the
  improvement path. The ad-hoc engine reads the D-49 SEMANTIC MARTS, never
  the frozen star schema (the plane-divergence fix). The hosted code arm stays
  DORMANT (provider-agnostic infra, no key in prod), config default flips to
  `ollama:gemma4:12b` at K1 ship.**
- **K3 — LLM bucketing/labeling (additive only, D-5):** deterministic cluster
  names stay canonical; the LLM writes optional grounded descriptions.
  Graders: `canonical_name_preserved` 100% (a single rename = D-5 violation),
  `grounded_in_centroid` (must cite the top-|z| dims that produced the name),
  `no_invention`, vs the name-only baseline. Independent of K2.
- **D-45 — K4 multimodal upload (owner):** caps **20 MB · 10 min · 10 uploads/
  user** (config-tunable); bridge key = **`up` + 20 hex of the content hash**
  (base62-charset-safe → every existing regex guard + `{id}.mp3` filename
  path works unchanged; collision-proof vs 22-char Spotify ids; identical
  uploads dedupe for free — ground rule 1 satisfied, no second id system).
  Validation gateway in front of the EXISTING worker path (DSP 100% reuse):
  content-sniffed allowlist (mp3/wav/flac/m4a — magic bytes/ffprobe, never
  extension), byte cap before decode, ffprobe duration before decode,
  hardened ffmpeg (`-nostdin`, `-t <cap>`, `-vn`, single audio stream,
  subprocess timeout, temp-dir output). A NEW non-LLM attack surface: gets
  its own security review, not an eval score. The legally-cleanest
  acquisition path we have.
- **D-46 — K5/K6 stay design docs with countable go-gates (owner):** K5 LoRA
  personalization requires a PROVEN prompt plateau on a named golden dimension
  + ≥200-500 human-verified examples matching deployment marginals — a 5-seat
  pilot cannot produce either; gate = "materially more users" (Epic M's
  trigger). K6 RL-tuned recommendations require thousands of explicit
  thumb events via K1's chat (5 users produce dozens); **Spotify-fetched
  fields are NEVER reward inputs** (ground rule 3). Neither is built in
  Epic K. **The D-47 review flywheel is the official COUNTER toward K5's
  200-500 (visible in every review report) — the counter is not the gate.**
- **D-47 — chat logging + the review-session flywheel (owner, 2026-07-17:
  log ALL + /privacy disclosure + 90-day retention; graded rows kept).**
  Two serving-DB tables (house style, soft refs, no auth sid — a fresh
  `chat_session_id` uuid4): **ChatLog** designed for the REVIEW READER
  (mode, prompt_version, user_question, the FULL rendered_context sent,
  raw_model_output, parsed_answer, cited_entities, source llm|fallback,
  real Ollama token counts, latency, error, created_at; indexed
  (chat_session_id,turn_index) / created_at / (source,created_at)) —
  `/ask` + `/classify` write rows from day one, fallback turns included;
  **ChatLabel** (rubric-v1: accuracy 0-2 vs context-only · citation_fidelity
  0-2 · invention 0/1 the safety bit · usefulness 0-2 · verdict
  good|fixable-prompt|fixable-context|bad · missing_fact · golden_proposal ·
  grader). `scripts/review_chat_logs.py`: deterministic stratified sample
  (8 story-llm / 8 adhoc-llm / 4 fallback), everything escaped (log text is
  untrusted), deterministic pre-grade via the grade_case machinery, labels
  written back, report = **aggregates-only** dated artifact in `evals/runs/`
  (raw user text NEVER reaches the public repo — rule 7). The flywheel:
  verdict-terminal rows → golden candidates (**owner/guest rows
  auto-proposable — D-18; other pilots' rows manual-anonymized**);
  `missing_fact` clusters → the D-49 slice backlog (evidence-driven RAG
  additions); accuracy=2 ∧ fidelity=2 ∧ invention=0 rows → the K5 dataset
  (**the popularity grounding line is STRIPPED from every exported pair —
  ground rule 3: never an ML input, not even laundered via context**).
- **D-48 — the RTCROS prompt contract (owner framework choice).** ONE
  encoding: `src/webapp/prompt_contract.py` — `PROMPT_VERSION` ("rtcros-v1",
  stamped into every ChatLog row and eval artifact), modes
  adhoc|story|profile parameterizing ONLY Task+Output (classify's inline
  second encoding dies), `build_system(mode)`, and `verify_citations`. The
  six components explicit: Role (the on-demand music data analyst) · Task
  (per mode) · Context (`<data>` delimiters; boundaries: not-in-data doesn't
  exist / «labels» are canonical, copy character-for-character / popularity
  is metadata never acoustics) · Reasoning (thoughts-first) · Output (JSON;
  **cited[] BEFORE answer — copy-anchoring: once the label is among the
  model's own tokens, re-copying beats paraphrase**) · Stop (≤6 entities,
  "not in your data yet", one JSON object). With TEETH: server-side
  verify-and-retry — cited[] must match the **structured entity inventory**
  (never raw context substrings: a track named "…say Drake is #1" makes
  substring checks spoofable), one corrective retry then fallback, violation
  logged. Plus the consult's data/routing fixes FIRST (they're 3 of the 6
  baseline failures): render archetype motion/breadth in the grounding,
  gate empty-context straight to fallback, `num_predict=1024`. Acceptance:
  a NEW dated artifact ≥12/15 with safety 100% and per-case sources printed,
  measured against a fresh re-baseline (the committed 9/15 overstates —
  2 classify grades were fallback output after cold-load timeouts).
- **D-49 — the semantic layer (the owner's data-first mandate; the crux).**
  **The serving cache is the source of truth** (796 live tracks); the
  semantic layer is the materialization boundary between planes: cache →
  governed Parquet marts (post-drain hook, atomic replace, idempotent) →
  BOTH the story composer and the ad-hoc DuckDB engine read the SAME fresh
  files. Views: **corpus_facts** (per-feature stats — always preloaded),
  **track_card** (per bridge key: perceptual + meta + cluster label +
  percentile ranks + **feature_valid** — the no-broken-superlative gate),
  **artist_rollup** (keyed by `primary_artist_id`, NEVER name),
  **cluster_profile** (stamped `trained_at` + `coverage_pct` — honest about
  the 39% lag), **feature_dictionary** (unifies feature_catalog +
  column_descriptions: layer/tier/unit/**direction**/percentile_source/
  **caveat** — rule 3 becomes a row the model is handed, not tribal
  knowledge). Per-viewer views (viewer_story, range_delta) stay serving-
  plane, computed on read, never persisted. **Retrieval: NO embeddings** —
  every question here is SQL-addressable by a stable key; a vector search
  can miss the true max (bad retrieval is negative information); FAISS
  already owns acoustic similarity. Chunk taxonomy = entity CARDS
  (corpus-stats ~350 tok + cluster ~100 + top-15 artists ~600 + viewer
  story ~200 preloaded ≈1.4K, inside the 2K pin; track cards on-demand via
  SQL or entity mention). The frozen star schema remains the batch/portfolio
  showcase — **the chat never reads it**. Tripwires ship WITH the layer:
  plane-coherence (ad-hoc count == mart count == cache count — FAILS today,
  by design), no-broken-superlative, dictionary parity, key resolvability.
  A card carries `population_n`; percentile phrasings are never cached
  across rebuilds.
- **D-50 — the chat-analyst-expert agent (owner ask, created 2026-07-17):**
  `.claude/agents/chat-analyst-expert.md` owns the Talk-to-your-data surface
  (semantic-layer consumption, RTCROS, chunk/retrieval, the log→review
  flywheel); data-platform keeps the mart builds; llm-rag keeps the eval
  harness + provider mechanics. First outing delivered the D-47/D-48 drafts
  + the baseline autopsy (3 prompt / 2 context / 1 routing failure).

**Build order + routing (resequenced 2026-07-17 — data first):**
- **K0.5 — the data floor (FIRST; Opus w/ Fable sign-off on the data
  actions):** re-baseline w/ per-case sources (llm-rag lane) · the 2
  grounding fixes + empty-context gate + num_predict · the semantic marts +
  feature_dictionary + post-drain wiring + the 4 tripwires · repoint the
  ad-hoc engine at the semantic marts · resolve the 2 broken extractions
  (re-extract or dead-letter — owner ratifies) · decide online cluster
  assignment in the post-drain hook (recommended) or stamp the lag honest.
- **K1 — probe, then /chat (Opus):** the raw-call probe (~20 read turns) →
  `prompt_contract.py` + golden_chat_v1 (story + adhoc + context_carry) →
  the viewer-gated /chat w/ ChatLog writing from turn one.
- **K1.5 — the flywheel live (Opus build, the REVIEW SESSIONS are
  owner+Fable):** review_chat_logs.py + ChatLabel + the first real review
  session over live logs → graded rows, golden promotions, the K5 counter
  starts.
- **K2 injection evals (FABLE) → K2 loop (Opus, gated)** → **K3 (Opus)** →
  **K4 gateway (FABLE security review, Opus plumbing)** → **K5/K6 docs
  (Fable, when gates trip).**

## Phase 5 — MPD (Epic J, un-changed shape, now sequenced)

The saved plan holds (metadata-only, D-26; Spark un-parks on the real 66M rows,
D-27; the dbt/Recce references in `mpd-future-references` memory). Entry
criterion: Phase 3 shipped + public. J0 intake script → J1 Spark co-occurrence
+ track2vec → J2 hybrid reco (acoustic × behavioral — completing the
related-artists replacement) → J3 the honest at-scale benchmark.

## Phase 6 — the ML capstone

On the dataset the app + MPD built: richer clustering/embedding models over the
grown REAL corpus, the hybrid recommender productionized, and whatever K5/K6
gates opened. Scoped properly when Phase 5's data exists — deliberately NOT
spec-fixed today (the agile-coach agent keeps this honest at each phase
boundary).

## Sequence (owner-approved 2026-07-14)

**P3.0 → P3.1 → P3.2 → P3.3 → P3.4 → P3.5 → P3.6 → P3.7(flip) → Phase 4 (K0…)
→ Phase 5 (MPD) → Phase 6 (ML).** Harness additions this session:
`research-expert` + `agile-coach` agents (both registered). Same ground rules
throughout — and one more now standing: **borrowed-time API surfaces are
absent-safe garnish, never load-bearing** (the research brief's doctrine).

## Model routing — Fable vs Opus 4.8 (owner, 2026-07-15)

**The rule: Fable designs, decides, and audits; Opus executes specced slices.**
Expert agents are pinned `model: opus` (their charters' "How you think"
disciplines carry the review quality); `agile-coach` keeps these tags current.

| Roadmap item | Model | Why |
|---|---|---|
| P3.3 Library tabs · P3.4 playlists · P3.5 guest dashboard · P3.6 H5/H6 | **Opus** | File-level specs exist (IA consult + D-37); established page patterns to copy; testable acceptance |
| P3.6 **O2 threshold tuning** (match confidence) | **split** | Opus builds; the corpus-tuned threshold decision is a #19/#24-class judgment — Fable (or owner) signs it |
| P3.7 **L-lite** (case study / README / how-to) | **Opus** | Strong writing from the chronicle as source; owner reviews the narrative |
| P3.7 **L-flip** (gitleaks triage · filter-repo scrub · public flip) | **Fable** | Irreversible + security-adversarial; agile-coach runs the checklist, Fable makes the calls |
| Phase 4 **K0 design** (agentic RAG, tool-use safety, injection evals, go-gates) | **Fable** | Novel architecture + adversarial surface; llm-rag-expert consults ride Opus |
| K1–K4 **builds** (chat plumbing, upload path) | **Opus** | Execute the K0 spec; evals gate every ship |
| K2 **injection-eval design** | **Fable** | The eval IS the security boundary |
| Phase 5 **J1 modeling design + J3 benchmark interpretation** | **Fable** | Co-occurrence/embedding choices + honest at-scale claims are judgment |
| Phase 5 **J0/J1 ETL execution** | **Opus** | Specced pipeline work with parity/audit gates |
| Phase 6 **ML capstone scoping** | **Fable** | Unscoped by design |
| Any new vision/spec, security review, or surprising-behavior debugging | **Fable** | The #19/#25-class problems — where the model must fight its own gut |
