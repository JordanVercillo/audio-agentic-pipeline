# Phase 5 — AcousticBrainz at scale: the executable spec (F1)

**Designed 2026-07-29 (session 64, Fable lead + dsp / data-platform / research
consults; full reports in the session-64 chronicle entry). Decisions D-68…D-73
recorded in `VISION_SPECS.md` §Vision F. This spec is written to be executed
by Opus WITHOUT a further design session — every judgment call is pinned here
or in the decision records. Where this spec and a consult report disagree,
this spec wins; where both are silent, follow the named house pattern.**

**Anti-fossilization rule (journal #61):** the *Verified externals* below were
checked 2026-07-29. Facts marked `[intake-verify]` are derived from the
dump-generator source, not the bytes — J0b's schema-contract step re-verifies
every one against the actual files before anything downstream trusts them.
Corpus numbers (1,946 analyzed, 109 ISRCs, …) are that day's snapshot; every
script re-derives its own counts and no acceptance bar hard-codes them.

---

## 0. The claim discipline (D-68 — read first)

AcousticBrainz values come from Essentia's extractor — an independent,
*uncalibrated* estimator. MetaBrainz's own shutdown post says the BPM values
are "incorrect" for many recordings, the key data is accurate "on some styles
… not the full range", and the data "is unable to indicate a confidence
level". Therefore:

- The harness measures **CONCORDANCE between two uncalibrated estimators**.
  The word "validate" and the phrase "ground truth" are banned from code,
  captions, README, and case study for this plane.
- Public claim template: *"our locally-extracted features agree with an
  independent 7.6M-recording reference at X% (per dimension, per tolerance
  class)"* — with the coverage caveat (the joined subset skews pre-2022 and
  MB-curated; no rate extrapolates to the full corpus).
- A disagreement is a **hypothesis, never a verdict**. Only an adjudicated
  row (§4) licenses "we're wrong" (or "they're wrong").
- AB's missing confidence signal is replaced by **cross-submission
  agreement** (~3.9 submissions per recording in the dump): high-spread
  recordings are marked `comparable=False` and skipped — precision over
  recall, because a false "our DSP is wrong" could wrongly justify D-67's
  irreversible Tier-B re-extraction.
- The AB **live API is borrowed-time garnish** (answering 3.5 years past its
  announced shutdown): used only for adjudication-sample enrichment (§4),
  always absent-safe, never load-bearing. The 2.8 GB CC0 dump is the
  permanent asset.

## 1. Verified externals (2026-07-29 — re-verified at intake)

**Dump** (`data.metabrainz.org/pub/musicbrainz/acousticbrainz/dumps/
acousticbrainz-lowlevel-features-20220623/`): three `.tar.zst` + `sha256sums`;
each tarball = one CSV + COPYING. `[intake-verify]` columns (from
`db/dump.py` at generating commit `93d777f0`):

- `lowlevel.csv`: `mbid, submission_offset, average_loudness,
  dynamic_complexity, mfcc_zero_mean`
- `rhythm.csv`: `mbid, submission_offset, bpm,
  bpm_histogram_first_peak_bpm_mean, bpm_histogram_first_peak_bpm_median,
  bpm_histogram_second_peak_bpm_mean, bpm_histogram_second_peak_bpm_median,
  danceability, onset_rate`
- `tonal.csv`: `mbid, submission_offset, key_key, key_scale,
  tuning_frequency, tuning_equal_tempered_deviation`

Facts that shape everything: **grain is (mbid, submission_offset)** — 29.46M
submission rows over **7.56M unique recordings** (~3.9×, capped ~10);
**all values are TEXT** (JSONB `->>`), empty string = missing, CRLF line ends,
header row present and authoritative; `mbid` can occasionally be a MessyBrainz
id (`gid_type` not dumped — such rows simply never resolve, an honest miss);
**no** artist/title/duration/date/ISRC/version/confidence columns; no
`beats_count`, no `key_edma`/`key_krumhansl` triple, no `chords_key` (those
live in the big JSON dumps / live API only — see §4 sample enrichment).

**MusicBrainz** (measured live): batched Lucene ISRC search works —
`query=isrc:A OR isrc:B…`, each returned recording carries its `isrcs` array
for attribution; verified OK at 256 clauses, fails ~300 (URL ~6–7 KB is the
binding limit, ~23 bytes/clause); **`limit` max 100 and out-of-range values
silently degrade to 25** (always pass `limit=100` explicitly and page on
`count`); ~12.5% of ISRCs return multiple recordings; search results include
`length`, `first-release-date`, `disambiguation`, `releases[]`; the dedicated
`/ws/2/isrc/{isrc}` endpoint cannot batch and **silently ignores
`inc=releases`** — use search. Rate limit 1 req/s (a batch = ONE request);
mandatory contactful User-Agent; throttle response is 503. MB `length` is
often rounded to whole seconds and can tie exactly across studio/live
recordings — duration alone never decides a match (D-72).

**Local prerequisite (measured):** ISRC exists for ~109 of 1,946 analyzed
tracks (5.6%) — the corpus arrived via playlists into a cache that never had
an `isrc` column. D-70 fixes this in P4.6.6 at zero marginal API cost.
`src/warehouse/modeled.py:_build_dim_tracks` silently drops requested columns
missing upstream (`available = [c for c in dim_cols if c in …]`) — D-70 adds
a warning/tripwire so a column can never vanish unnoticed again.

## 2. Slices

### J0a — ISRC + release-date supply (rides P4.6.6, D-70; BLOCKS J0.5)

`TrackMeta.isrc` (forward-only column, preserve-if-absent — the exact
`popularity` pattern); `remember_meta` threads it; `fetchers.py` already
parses `external_ids.isrc` (lines 363/714) so ingestion captures it from now
on; `backfill_album_meta.py` (P4.6.6) writes it for the backlog from the same
batched `/tracks?ids=` responses it already makes. Acceptance: post-backfill
`SELECT COUNT(*) FROM track_meta WHERE isrc IS NOT NULL` ≥ 90% of analyzed;
the `_build_dim_tracks` silent-drop gets a warning + test.

### J0b — dump intake

Owner hand: download the three tarballs + `sha256sums`; verify checksums
before anything parses (record in `SOURCE.json`: url, bytes, sha256,
downloaded_at, dump_date, license=CC0).

Layout (AB is a **foreign reference plane — deliberately OUTSIDE
`data/warehouse/`** so the audit walker's bridge-key/82-col rules never see
it; never name an AB artifact `*_features.parquet`):

```
data/acousticbrainz/            # gitignored
  raw/                          # immutable: 3 CSVs + COPYING + SOURCE.json
  staged/{lowlevel,rhythm,tonal}/bucket=<hex>/part-000.parquet
  recording/bucket=<hex>/       # ab_recording: deduped, 1 row per mbid (~7.56M)
  cache/musicbrainz/            # J0.5 response cache, one JSON per ISRC
  _manifest/intake_manifest.parquet
contracts/acousticbrainz_v1.json   # CHECKED IN — the schema contract
```

Pinned mechanics: **16 buckets on the literal first hex char of `mbid`**
(never an engine `hash()` — DuckDB's and Spark's differ, and identical
bucketing is what makes J2 parity bucket-local); `ORDER BY mbid` within
bucket; explicit dtype casts from the contract (never sniff — TEXT source,
mid-file cast traps); range checks warn-never-fail; bucket-skew assertion
(max/min ≤ 1.2 — catches non-uniform ids incl. the MSID case). Schema
contract: first run `--adopt-contract` writes the ordered column list +
dtypes from header + 50k-row sample, owner-reviewed, committed; every later
run asserts ordered-equality and exits non-zero naming any diff; a
required-column gate (`mbid`, `submission_offset`, `bpm`,
`bpm_histogram_second_peak_bpm_median`, `key_key`, `key_scale`,
`tuning_frequency`, `dynamic_complexity`) fails fast pre-parse.
Idempotency: per-table `.tmp_` dir + atomic rename, startup `.tmp_*` sweep,
manifest rows carry rows + **content-hash** (canonical-order logical rows —
the portable invariant) + file-hash (env-pinned) + tool versions. Re-run of a
landed table with matching hashes = no-op.

### J0.5 — the bridge

`src/ingestion/musicbrainz.py`: batched search client — **50 ISRCs/request**
(headroom under both the URL and the 100-result page limits), explicit
`limit=100`, offset paging when `count` > page, pacer `MB_MIN_INTERVAL_S=1.1`
(monotonic clock, the D-64 idiom), mandatory
`VercilloAnalytics/<ver> ( vercillojordan@gmail.com )` UA (test: non-default,
contains `@`), response cache one-file-per-ISRC (tmp+replace; zero-byte or
unparseable = absent; 404 permanent, 5xx retryable), absent-safe on
no-ISRC. Whole corpus ≈ 40 requests < 1 min; re-runs zero requests.

**D-72 resolution policy** (an ISRC returning multiple recordings): keep
candidates whose `length` is within ±3 s of our `duration_ms` (MB rounds to
seconds — never require equality) → reject candidates whose
`disambiguation`/title carries a reproduction marker (live / karaoke /
instrumental / demo — reuse `match_gate`'s marker vocabulary) unless our own
title carries it → among survivors prefer one with an AB row → still tied →
`isrc_ambiguous`, an honest miss. A wrong MBID **fabricates a disagreement**
— precision over recall, in the docstring.

`data/marts/ab_bridge.parquet` — grain **one row per `spotify_track_id` in
the attempted set, misses included** (a missing row corrupts the coverage
denominator — journal #60 applied to both sides of the fraction). Columns:
`spotify_track_id (PK) · isrc · mbid (nullable attr — NEVER unique: ~8% of
ISRCs legitimately map 2 corpus tracks to one recording) · mb_length_ms ·
mb_first_release_date · mb_match_type · mb_candidates_n · ab_row_present ·
miss_reason ∈ {no_isrc, isrc_unresolved, isrc_ambiguous, mbid_not_in_ab,
post_dump_release} (closed enum, never null on a miss) · resolved_at ·
ab_dump_version`. Coverage report → dated `evals/runs/…_ab_bridge_coverage.txt`
with every miss bucketed + release-year distribution of the post-dump bucket.
**Pre-registered prediction (on the record before measurement): 50–62%
coverage, post-dump releases the largest miss bucket.** The
`AB_COVERAGE_FLOOR` pin is written only after the first post-backfill run,
and the pinning step refuses while `no_isrc` is the largest bucket.

### J1 — dedup + the concordance harness

**D-71 submission→recording dedup** (`ab_recording`, 1 row per mbid):
numerics collapse by **`PERCENTILE_DISC(0.5)`** — explicitly not
`np.median`'s interpolation, not `percentile_approx`; this is what makes
pandas/DuckDB/Spark byte-agree, and the J2-A parity target is exact because
of it. Categoricals by mode, ties lowest-lexicographic. Carried quality
columns: `n_submissions`, `bpm_mad`, `key_agreement` (winning fraction).
Trust filter: `comparable=False` when `bpm_mad > 2` (tempo) or
`key_agreement < 0.6` (key) — skipped, counted, never scored.

**Comparison surface** (everything else is rejected in D-69's mapping table —
notably loudness vs `average_loudness` is dishonest because our loader
peak-normalizes, and MFCC/rolloff/centroid are censored by our 22.05 kHz
Nyquist):

| Ours | Theirs | Method |
|---|---|---|
| `tempo_bpm` (+ v2 candidates: median-IBI, k-lag rate) | `bpm` | log-ratio classes |
| `estimated_key`+`estimated_mode` | `key_key`+`key_scale` | pitch-class map (enharmonic-safe), tonic/mode marginals |
| loudness-curve mean abs dB deviation | `dynamic_complexity` | **rank-only** Spearman (predict ρ 0.3–0.6; audits the UI "dynamics" claim) |
| — | `bpm_histogram_second_peak_bpm_median` | ambiguity signal: second peak ≈ our bpm (±4%) ⇒ metrically ambiguous, neither wrong |
| — | `tuning_frequency` | confound detector for SEMITONE class only |

**Version gate (before any scoring):** AB CSVs carry no duration, so the
gate uses the bridge's `mb_length_ms`: `|our duration_sec·1000 −
mb_length_ms| / mb_length_ms ≤ 0.02` (tolerant of MB whole-second rounding).
Failures are the ACQUISITION class → provenance-QA flywheel, not estimator
rows. Report n at every gate: analyzed → bridged → ab-covered →
version-passed → comparable.

**D-69 tempo taxonomy** (log-ratio ρ = log₂(ours/theirs); class = nearest
r ∈ {1, 2, ½, 3, ⅓, 3/2, ⅔} within log₂(1.04); absolute-BPM bands are
rejected — they'd score our own 20-point grid quantization as error):
`AGREE` (r=1 ≤4%) · `AGREE_TIGHT` (≤2%, the v2 sensitivity metric) ·
`MARGINAL` (4–8%, adjudicated) · `OCTAVE_WE_DOUBLE`/`WE_HALF` ·
`TRIPLE_FAST/SLOW` · `COMPOUND` · `GRID_CENSORED` (AB bpm outside our
[69.8, 172.3] grid — flagged before ratio classing) · `SEMITONE_RESAMPLE`
(2^(±1..2/12) AND inverse duration ratio — acquisition, not estimation) ·
`RESIDUAL`. **Pre-registered, falsifiable:** `OCTAVE_WE_DOUBLE` ≥ 3×
`OCTAVE_WE_HALF` (the sub-92-bpm corpus deficit reads as double-time tactus
bias); if it comes out backwards, publish that instead. **First probe before
trusting any band:** count distinct `bpm` values on the joined subset — if AB
is also quantized, widen every band and say so.

**Key classes:** report `EXACT`, `TONIC_AGREE`, `MODE_AGREE` always together;
near-miss classes `PARALLEL` (the measured leading weakness — 25.1% runner-up
share; mediant-bin decision) · `RELATIVE` · `FIFTH_DOM/SUBDOM` · `SEMITONE`
(tuning/resample — cross-check `tuning_frequency` + duration) · `OTHER`.
Every key disagreement carries the free per-track evidence: mediant ratio
(b3/M3 from stored chroma), KK margin, and — sample-scale only — live-API
`key_strength`/`chords_key`. A PARALLEL row whose own mediant contradicts our
label is *our* bug; one in the ambiguous [0.9, 1.1] band is "unresolvable
from this representation" — an honest third state.

**Output:** `data/marts/ab_corroboration.parquet` — **long form**, one row
per (`spotify_track_id`, `metric`): `ours, theirs, ratio, class, comparable,
n_submissions, ab_spread, evidence fields, adjudicated_by, winner,
dsp_version, ab_dump_version`. Adds nothing to `track_features`; the 77-dim
vector and 82/83-col dict are untouched (this plane READS). Dated artifact:
`evals/runs/…_ab_corroboration_j1.txt` (per-metric agreement + the
double/half-time table = D-67's F16 evidence).

### J1-adjudication (§4 of D-69)

Stage 0 auto-triage (free, every disagreement): version-gate delta, AB
second-peak ambiguity, our KK margin + mediant, `tempo_bpm` vs our own
shipped beat grid (63 tracks already internally inconsistent >4% — a defect
on its own terms, no AB needed), per-section tempo spread (genuinely
tempo-variable tracks have no single answer). Buckets: LIKELY-OURS /
LIKELY-THEIRS-or-AMBIGUOUS / UNRESOLVED.

Stage 1 owner listening (the gold): n=20 per class, fixed seed, stratified,
**preferentially from the ~117 local-audio tracks** (no re-download); classes
with <30 members report "insufficient n" and get NO rate (journal #28). Clip
= 15 s from the 2nd stored section boundary. Tempo: click-track A/B at both
candidate rates ("both work" = AMBIGUOUS). Key: tonic drone + third per
candidate. ~20 min per class. Priority: OCTAVE_WE_DOUBLE → PARALLEL →
RELATIVE → RESIDUAL → GRID_CENSORED → MARGINAL. Stage 2: published
references, sample-only, evaluation-only (the D-65 line). n=20 establishes
*direction*, not a calibrated rate — the writeup says so.

### J2 — the at-scale jobs (DuckDB production + Spark parity)

- **J2-A** the D-71 dedup itself: 29.46M → 7.56M, the phase's one genuine
  shuffle; parity target EXACT (that's what `PERCENTILE_DISC` buys).
- **J2-B** percentile grid: 100 `PERCENTILE_DISC` cutpoints per metric over
  the deduped plane → `data/marts/ab_corpus_stats.parquet`
  (metric, percentile, value, population_n) — ships the product line "your
  track's tempo sits at the Nth percentile of 7.56M recordings". No
  year/genre slices — the dump has no such columns.
- **J2-C** broadcast top-k neighbours over the shared subspace (tempo +
  dynamic-complexity + key as filters — the honest label is *"closest on
  measured tempo/dynamics"*, NEVER "sounds alike"; D-65's discipline).
  Map-side broadcast, no shuffle — the genuinely Spark-shaped job.

`spark/ab_jobs.py` + `parity_check.py --real` mode: runs against
`data/acousticbrainz/staged/` when present, **skips with a clear message when
absent** (CI stays synthetic — no 2.8 GB in CI, non-negotiable). Parity
gates timing: a failed-parity run reports no benchmark number.

**Benchmark protocol:** identical staged Parquet for both engines; hardware
stated; DuckDB `threads=16` vs Spark `local[16]` JDK 17; 1 cold + 3 warm
(median of warm + min/max + cold); `jvm_startup_s` reported separately,
never folded, never hidden; second config memory-capped (DuckDB
`memory_limit='4GB'`, Spark driver 4g / `shuffle.partitions=64`) — where
graceful-spill-vs-OOM actually distinguishes the engines; **zero synthetic
rows — N is 29,460,584 because that is how many rows exist.**
**Pre-registered prediction: DuckDB wins single-node on all three jobs; the
honest story is the capped-memory behavior, and that is a better portfolio
finding than a rigged Spark win.** Dated artifact:
`evals/runs/…_ab_parity_benchmark.txt`.

### J3 — the writeup + the F2 verdict (D-73)

Case-study section under the D-68 claim discipline; the coverage caveat in
the same paragraph as every headline rate; the "behavioral similarity has no
legal source" gap stated (unchanged from D-65). Then the **F2 memo** applying
D-73's bars to the measured evidence, ending in exactly one of the three
verdicts per estimator (ADOPT v2 / KEEP v1 FOREVER / SOFTEN THE CLAIM), each
publishable. Any ADOPT escalates to the owner as a D-67 Tier A/B decision
with the full blast radius named: a `tempo_bpm` change forces a full re-extraction,
cluster retrain (D-62 machinery), perceptual blend shifts, gold re-export.

## 3. The D-73 evidence bars (frozen before the join runs)

Pre-registration = this spec: bands, classes, base rates
(tempo AGREE 55–70%, AGREE_TIGHT v1 30–45%, octave-double 10–20%; key EXACT
35–50%, PARALLEL 18–28%, MODE_AGREE 55–65%), seeds, n. Deviations get
recorded, not re-tuned.

**Tempo v2 proposes a bump only if ALL hold:** ① `AGREE_TIGHT@2%` +≥8 pts
and median abs relative error −≥0.5 pts with bootstrap 95% CI excluding 0
(inside r=1); ② non-r=1 share worsens ≤0.5 pts (v2 shares the beat grid —
it CANNOT fix octaves, and must not be credited for them); ③ internal
consistency with our shipped beat grid ≤1% for ≥99% of tracks (v1 today: 63
tracks >4%, max 6.7%); ④ named-song pins: ≥12 owner-known tempos within ±2%
of published, zero pins move from inside to outside (anchors: Seven Nation
Army 123.0/IBI 122.4 · Billie Jean 117.5/117.6 · Smells Like Teen Spirit
117.5/117.6 · Bohemian Rhapsody (P!ATD) 143.6/142.9; Money `time_signature=7`
re-asserted unchanged — a scope anchor, not an accuracy anchor); ⑤ Tier A
A/B on the local MP3s reproduces the other 76 dims bit-identically.

**Mode v2 (deliberately harder):** ① baselines as pre-registered; ② MODE_AGREE
+≥10 pts AND corpus major share lands in [60, 72]% AND TONIC_AGREE degrades
≤2 pts (a mode fix that churns tonics is a regression in a win's clothes);
③ ≥15 named-key pins — fixes ≥4 currently-wrong (Uprising D-major→minor,
Money A-major→B-minor) with zero regressions on currently-right (7NA Em,
Billie Jean F♯m, SLTS Fm, BoRhap B♭); ④ signal-support precondition: on the
adjudicated PARALLEL sample, ≥60% must show our own mediant contradicting our
label — otherwise no profile tweak can honestly fix it → verdict ③.

**The three verdicts (all publishable):** ADOPT v2 (owner-signed D-67
escalation) · KEEP v1 FOREVER ("our quantization sits below the noise floor
of the best independent reference available" — a finding, not a failure) ·
**SOFTEN THE CLAIM** — ship a confidence display ("D minor · low confidence"
from the KK margin; 11.8% of tracks sit under 0.02) as a forward-only
DISPLAY column: no vector change, no re-extraction, no owner-signed
irreversible. Spec it in parallel so a mode-v2 failure still ships product
value.

## 4. Audit + tests

New `check_acousticbrainz()` in `audit_warehouse.py` (house signature,
merged into the one flags dict; **entirely absent-safe** — a pre-Phase-5
tree emits nothing): `AB_BRIDGE_GRAIN` (dup/null bridge key) ·
`AB_BRIDGE_ORPHAN` (id outside canonical ∪ twins) · `AB_COVERAGE_FLOOR`
(**two-sided**: rate < pinned floor − 2pp OR absolute matched count
decreases — journal #60's one-sided-bound lesson head-on) ·
`AB_MISS_UNEXPLAINED` (unmatched row with null/off-enum reason) ·
`AB_SCHEMA_CONTRACT` (staged columns ≠ contract) · `AB_DEDUP_GRAIN` (dup
mbid in ab_recording) · `AB_VERSION_SKEW` (>1 dsp_version or
ab_dump_version in ab_corroboration; names the ledger during a planned
Tier-A A/B). **Deliberately NOT a flag: the disagreement rate** — it is the
phase's product; a flag there pressures suppressing findings.

Tripwire tests (synthetic, no dump needed — a 20-row fixture Parquet):
`test_ab_dedup_is_percentile_disc` ([100,110,120,130] → **110**, not 115 —
kills the engine-divergence class) · `test_ab_bridge_absent_safe` (no ISRC →
one row, miss_reason=no_isrc, never dropped) · `test_coverage_floor_fires`
(one-below-floor → red; a flag never fired is decoration) ·
`test_ab_schema_contract_rejects_rename` · `test_mb_client_zero_requests_when_cached`
· `test_mb_pacer_min_interval` (fake clock ≥1.1 s) ·
`test_mb_limit_always_explicit` (the silent-25 trap) ·
`test_ab_shared_mbid_is_not_a_duplicate` (two tracks, one mbid → every grain
check passes) · 12 tempo-class fixtures incl. 3.9/4.1% and 7.9/8.1%
boundaries · 12 key fixtures incl. enharmonic Ab/G# both directions ·
pitch-name→pitch-class table test · version-gate 1.9/2.1% ·
`test_insufficient_n_refuses_rate` (2 rows → no rate; journal #28).

## 5. Session plan (Opus, after Vision F's S-series)

| Session | Contents | Gate |
|---|---|---|
| **P5-S1** | J0a lands with P4.6.6 (D-70) · `musicbrainz.py` client + tests · `_build_dim_tracks` warning | backfill ≥90%; client tests green |
| **P5-S2** | owner downloads dump (sha256-verified) · J0b intake + contract adopt (owner reviews contract) · bucket-skew + manifest green | staged plane + committed contract |
| **P5-S3** | J0.5 bridge run · coverage report · floor pinned (post-backfill only) · audit flags + tests | the gating number, explained |
| **P5-S4** | J1 dedup + harness + Stage-0 triage · the J1 artifact | ab_corroboration + report; owner reads the class table |
| **P5-S5** | Stage-1 adjudication (owner, ~2 h listening across classes) · Stage-2 refs | adjudicated rows recorded |
| **P5-S6** | J2 jobs + parity + benchmark (JDK 17 prerequisite from Vision F S1) | parity green; dated benchmark artifact |
| **P5-S7** | J3 writeup + F2 verdict memo (D-73) | one verdict per estimator; owner signs any ADOPT |

Owner hands in the plan: the dump download (P5-S2), the contract review
(P5-S2), the listening sessions (P5-S5), any ADOPT escalation (P5-S7).
