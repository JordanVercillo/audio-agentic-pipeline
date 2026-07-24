# QA & bug-fix plan — Epic QA (owner ask, 2026-07-23)

Written at the end of a very long build session so the next one starts from
this file, not from a lost conversation. Everything below is either **verified
live** or an **open item with its evidence**.

**Updated 2026-07-23 (session 57).** QA1, QA2/B1 and B2 are shipped; the queue
drain is done and converged. The standing regression sweep is now
`scripts/qa_audit.py` — run that first, it answers most of this document.

## Where we are

**Phase 4.5 (Epic Q — provenance & QA).** Q1 (capture) ✅, Q2 (exposure) ✅,
Q3 (the D-52 full re-extraction) ✅, D-56 (owner repair) ✅, D-57 (withhold
unverified) ✅, **QA1 (the sweep) ✅, QA2/B1 (one guarded acquisition path) ✅,
B2 (unvalidated leave the aggregates) ✅, B3 (drain) ✅ converged.**

Corpus truth (measured 2026-07-23 after the drain + B2 retrain):

| metric | value |
|---|---|
| canonical analyzed | **771** |
| source-validated (has provenance) | **731** |
| **unvalidated** (features withheld from display AND aggregates) | **40** |
| **aggregate corpus** (clusters, /explore, marts, chat) | **731** |
| needs-source repair queue | **65** (was 72) |
| flagged duplicate twins | 35 (10 analyzed) |
| tests | **573 green** · ruff clean · app-verify ALL-FALSE |
| `qa_audit.py` | **0 failed · 7 passed · 2 notes** |

Cluster model #9: k=2, silhouette **0.174** (was 0.172), buckets unchanged
(`Gentle · Noisy` / `Punchy · Smooth`), archetype unchanged
(**The Drifting Loyalist**, σ-shift 0.185).

---

## A. Bugs found and fixed (each now has a standing check)

`scripts/qa_audit.py` runs these against LIVE data on demand. Almost none were
catchable by the unit suite — they only appeared when the feature was used.

| # | Bug | Root cause | Standing check |
|---|---|---|---|
| A1 | DJ-set audio stored as songs (19 tracks, up to 37× too long) | heuristic-v1 **ranks, never rejects** | `duration_sanity` ✓ |
| A2 | **Wrong songs entirely** (7 of the first 71 swaps) | duration scored +25 with no title requirement | `title_affinity` ✓ + `confident_match` note |
| A3 | 27 wrong-song swaps **grandfathered** past the resume marker | a resume key records *that* work happened, not that it was correct (journal #46) | `title_affinity` ✓ (reuses the gate's own function) |
| A4 | Every repair silently failed at conversion | **Anaconda's ffmpeg** (no libmp3lame) shadowed the good build (journal #47) | `mp3_encoder` ✓ |
| A5 | Repairs left **stale derived planes** | swap updated `TrackFeatures`; `/explore`, chat read `track_perceptual` + marts | `plane_coherence` ✓ |
| A6 | 20 MB cap made lossless masters impossible | D-45's cap was specced for **public** uploads | `upload_cap` ✓ |
| A7 | Owner repair tools hidden by the D-57 gate | the gate wrapped the whole analyzed block | route test in suite |
| A8 | "117 bpm" vs "112 bpm" on the same audio | headline = periodicity; section = density | template + unit test |
| **A9** | **The guards themselves still admitted 4 wrong songs in 11** | affinity fired on one common token; duration was one-sided; remakes were invisible (journal #48) | `confident_match`, and the gate itself |

---

## B. Open items (ranked)

### ✅ B1 — CLOSED. One guarded acquisition path.
`extractor.default_acquire` now delegates to `re_extract.guarded_acquire` over
`src/ingestion/match_gate.py`. The live worker refuses a DJ set and a
wrong-title candidate **before downloading**; `qa_audit`'s `shared_gate` check
drives that path behaviourally so the divergence cannot come back.

### ✅ B2 — CLOSED. Unvalidated features left the aggregates.
`cache.excluded_from_aggregates()` = twins | unvalidated is THE one population
filter (perceptual plane + prune, both cluster trainings, `similar()`).
Aggregate corpus 771 → 731; archetype did **not** shift. `corpus_facts` gained
`n_withheld_unvalidated` so "withheld" stays distinguishable from "gone".
**Fail-safe:** with zero provenance rows nothing counts as unvalidated — an
exclusion rule must not be able to exclude everything (journal #50).

### ✅ B3 — CLOSED (converged). The queue drained 72 → 65.
`scripts/drain_repair_queue.py` at the channel-verified bar (artist's own or
`X - Topic` channel, title containment, Δ≤10 s, no remake markers). Seven
repaired, each verified by hand against its stored provenance. A repeat pass
repaired 0.

**The remaining 65 are genuinely manual** — this is the honest ceiling, not a
backlog to grind: **44 have no plausible YouTube candidate at all** (obscure UK
garage / bassline / white-label imports), the rest only ambiguous ones. They
are the D-56 flow's job: `/library?filter=needs-source` → paste a link or
upload audio. Each repair refreshes the derived planes and returns the track to
every aggregate.

### B4 — the 6 long-duration tracks *(open, low)*
`FEATURE_DISTRIBUTION` is true solely because 6 tracks exceed 1 h (longest now
~2 h). They pass title affinity, so they're plausibly real DJ-mix releases —
eyeball and either confirm or queue for repair.

### B5 — DUPLICATE_TRACKS advisory on the frozen star schema *(open, low)*
10 near-dupe clusters in `dim_tracks` (the Jul-4 frozen warehouse plane, not
the serving corpus — O3 handles serving-side dedup). Decide: rebuild that
plane, or document it as intentionally frozen.

### B6 — error messages that lied *(partly done)*
Acquisition now says what actually happened ("no usable source — title
mismatch…") instead of "download failed". **Still to do:** sweep the other
user-facing failure strings for the same pattern.

### B7 — deferred, unchanged
S4 DMARC `quarantine`→`reject` (owner's DNS, ~Jul-25 after clean reports) ·
O3d acoustic recall miner · cluster_profile online-assign · `/chat`
async-streaming.

---

## C. What's left of Q4

1. ~~QA1 `scripts/qa_audit.py`~~ ✅ shipped.
2. ~~QA2 (B1) the shared guarded acquisition path~~ ✅ shipped.
3. **QA3 — `review_provenance.py`**: stratified sample of the provenance mart
   + duration audit → aggregates-only dated health artifact in `evals/runs/`,
   mirroring the D-47 chat-review flywheel. `qa_audit.py` covers the
   invariants; this is the *sampled human read* on match quality.
4. ~~QA4 (B2)~~ ✅ shipped.

**Definition of done for Epic Q:** `qa_audit.py` green on live data ✅ · the
worker and the runner share one guarded acquisition path ✅ · the needs-source
queue understood (drained to its honest floor + documented) ✅ · a provenance
health report committed — **QA3 is the one remaining item.**
