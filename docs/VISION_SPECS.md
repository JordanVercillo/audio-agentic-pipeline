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

Extends A3: **K0** eval extension (golden cases for bucketing + tool-use
traces) → **K1** LLM-assisted cluster naming/bucketing (gemma4 proposes names/
descriptions grounded on centroid z-features + exemplar tracks; deterministic
names stay canonical, LLM additive per D-5) → **K2** multi-turn `/chat`
grounded on taste + glossary + marts (8192-ctx budget management) → **K3**
tool-use over the **existing P5 read-only DuckDB core** (get_schema /
query_warehouse; D-10 sandbox; injection evals) — the literal target-JD line:
"systems that enable AI agents to interact with data infrastructure." Honest
risk: gemma4 tool-calling may under-perform → K3 is gated on K0 scores;
hosted-model fallback stays optional.

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

## Pilot trial — T0 OPENS NOW (2026-07-11, owner decision)

**2/5 Spotify dev-mode seats are filled** (the first pilot user added 07-09, the second pilot user 07-10)
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
(agentic chat) → L-flip (scrub + public GitHub)** · J parked · **pilot trial
runs throughout, starting T0 = 2026-07-11/12.** Every slice holds
the ground rules: bridge key, Parquet, PKCE-no-secret, synthetic tests
(code-correctness only — product data stays REAL), $0, evals before LLM
surfaces, live browser validation to close every build.
