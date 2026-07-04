# Engineering Journal — the surprises, numbered

One entry per genuine insight: a design assumption that broke, a surprising
result, a decision that only makes sense with its story. NOT a progress log
(that's `PROJECT_CONTEXT.md` §4). Format: title → situation → **The
realization:** → one-line `>` takeaway.

> *Capture the surprise, not the fix. The fix ends up in git; the lesson
> rarely does.*

---

## Foundation era (backfilled 2026-07-03 from the ADRs and docs)

### 1. The API deprecation was the best thing that happened to this project

Feb 2026: Spotify removed `/audio-features`, `/audio-analysis`, and
`popularity` for third-party apps. The original plan — pull Spotify's
danceability/energy columns and analyze them — died overnight.

**The realization:** the replacement architecture (YouTube acquisition →
local librosa DSP → own 77-dim feature space) is a far stronger portfolio
piece than consuming a vendor's precomputed columns ever was. The
deprecation forced building the interesting layer instead of renting it.
(Source: README, `.agent_prompts/01_spotify_api_guardrails.md`.)

> *When an upstream API removes your feature, check whether it just promoted
> your project from consumer to producer.*

### 2. The filename IS the join

ADR-005 names audio files `{spotify_track_id}.mp3`. No mapping table, no
manifest: any MP3 in `raw_audio/` joins to metadata via its filename stem,
and the DSP layer attaches the bridge key by parsing the path.

**The realization:** at this scale the filesystem is a perfectly good index —
one convention replaced a whole bookkeeping subsystem, and it made
idempotency trivial (`exists({id}.mp3)` = already downloaded).

> *Before building a lookup table, ask if a naming convention already is one.*

### 3. Scale-invariance decided the drift metric

Taste drift compares 77-dim centroids across time ranges. Features span
wildly different scales (tempo 60–200 BPM vs RMS 0–1), so Euclidean distance
would let tempo dominate everything. ADR-003 picked cosine distance.

**The realization:** the metric choice wasn't a math nicety — with
heterogeneous units, Euclidean drift would have been a tempo detector
wearing a taste-drift costume. (Same lesson family as the playbook's
"embeddings measure the words in the string": know what your metric
actually responds to.)

> *A distance metric is a claim about which differences matter. Make the
> claim on purpose.*

## Repo review era

### 4. The docs described the repo we meant to have (2026-07-03)

CLAUDE_INSTRUCTIONS ("everything ✅ Working", incl. a FastAPI webapp) and
PR_REFERENCE (branch, commits, diff stats) read as ground truth — but the
actual repo was two GitHub web-upload commits: nested duplicate folder,
committed `__pycache__`, no webapp anywhere, no trace of the described git
history.

**The realization:** documentation written during one copy's development
silently became fiction when the project moved via file upload instead of
push. Docs that assert state ("working", "complete") need a verifier — which
is exactly why the harness separates the frozen architecture manual from a
verified, session-updated PROJECT_CONTEXT, and why `warehouse-audit` exists:
claims about data get checked by a script, not trusted from a table.

> *A doc that says "✅ working" is a hypothesis until something re-runs the
> check. Keep aspirational docs and verified state in different files.*

---

## Phase V — verification

### 5. The secret sat directly under a comment warning about secrets (2026-07-03)

`auth.py` carried `_FALLBACK_CLIENT_SECRET = "9b75…"` right below the comment
"In production, always prefer environment variables for security" — and the
same pair lived on in legacy `spotify/spotify_config.py`. Both went to public
GitHub in the initial upload.

**The realization:** the fallback was added as a convenience during
single-machine development and became a leak the moment the repo went public —
the comment shows the author knew the rule and rated the risk zero. A
hardcoded-default credential is a secret leak with extra steps.
Scrubbed both files (env/.env only now), but git history still has it:
only rotating the secret in the dashboard actually closes it.

> *A secret with a "don't do this in production" comment is still a secret in
> production. Convenience fallbacks outlive the convenience.*

### 6. The run command in the docs didn't exist (2026-07-03)

Phase V's first step — `run_pipeline.py --skip-download --skip-extract` —
failed at argparse: the uploaded script was a notebook-runner (nbconvert on
`temporal_analysis.ipynb`, synthetic data by default) with only `--clean`.
The documented 7-step orchestrator, like the webapp (journal #4), existed
only in the Copilot copy. Yet every underlying module (fetchers, downloader,
extractor, warehouse) was real, tested, and interface-complete — rebuilding
the orchestrator was one session of wiring, no new logic.

**The realization:** the docs-fiction pattern (#4) reached the RUN COMMANDS —
the thing a verifier touches first. Which is exactly why verification caught
it immediately, and why the modules being genuinely tested made the fix cheap.

> *Verify the entry points first: they're where doc-fiction hurts most and
> where good module boundaries pay off fastest.*

### 7. "ffmpeg present" is not "ffmpeg capable" (2026-07-03)

First real run: 9/9 downloads failed. env-verify had checked `ffmpeg
-version` ✅. The actual error (found by re-running ONE download in the
foreground): `audio conversion failed: Encoder not found` — Anaconda's ffmpeg
ships without `libmp3lame`, and yt-dlp's MP3 postprocessor hardcodes that
encoder. Fix: Gyan full build via winget, first on PATH. (Also self-inflicted:
piping the batch run through `tail -80` discarded the diagnostic lines —
never truncate the only copy of a failure log.)

**The realization:** the env check validated presence when the pipeline needs
a capability. Same lesson family as #3 (know what your metric responds to):
know what your CHECK actually proves. env-verify now greps `-encoders` for
libmp3lame.

> *Test the capability you depend on, not the binary that claims to provide it.*

### 8. Two different 77s, and the warehouse got neither (2026-07-03)

First green-ish audit flagged FEATURE_DRIFT: 60 numeric feature cols vs the
77 contract. Investigation: `to_summary_vector()` (FAISS path) is exactly 77
— but `to_summary_dict()` (warehouse path) silently dropped `chroma_stds`
and `spectral_contrast_stds` (computed, never serialized: −19), while the
CLAUDE_INSTRUCTIONS feature table describes a DIFFERENT 77 including
bandwidth/flatness (never computed: −3) and excluding contrast_stds. Two
breakdowns, same total, both called "the 77-dim contract"; the warehouse
implemented the intersection. Fix: serialize everything computed + add
bandwidth/flatness → 82 numeric warehouse cols (vector untouched at 77);
audit tolerance ±7 → green.

**The realization:** a magic number is not a contract. Two documents agreed
on "77" while disagreeing on the members, and no consumer ever counted until
the audit script did. The instrument's first contact with real data found a
gap two documentation layers had papered over.

> *A contract is a column list, not a column count. If only a number is
> checked, only the number will be true.*

## Phase 5 — the insight layer

### 9. The metadata couldn't name the clusters — the features could (2026-07-03)

First taste-map render: all three clusters labeled "(Muse)" because one
artist dominates the corpus, and two shared the genre label "Indie & Alt" —
Spotify's sparse 2026 genre tags (36/117 tracks have none at all) plus a
dominant artist made metadata-based cluster naming degenerate. The fix came
from our own 77-dim space: z-score each cluster's centroid against the
corpus on interpretable dims and name clusters by what acoustically
distinguishes them — "Smooth · Dark" vs "Noisy · Bright" vs "Gentle · Loud"
(that last one is real: modern punk's compressed wall-of-sound is
sustained-loud with soft onset contrast).

**The realization:** this is the project's founding thesis eating its own
dog food. We built a local feature space because the vendor's acoustic
metadata disappeared; now the vendor's GENRE metadata proved too sparse to
even label clusters, and the local features did that job too.

> *When metadata can't differentiate your data, measurements can. Vendor
> labels are a convenience, not a foundation.*

### 10. The drift score flatlined at 0.0000 — then pegged at 1.4998 (2026-07-03)

First real run of the insight engine: Taste Drift Score **0.0000** across all
pairwise windows. Not "stable taste" — a broken instrument. Cosine distance
on RAW centroids is dominated by the largest-magnitude features
(spectral_rolloff ~8000 Hz vs rms ~0.1): the angle is pinned by two or three
big components while the per-feature deltas right below it showed real
3–9% shifts. The Copilot-era demo never caught this because its synthetic
data varied the dominant feature itself.

Fix #1 (z-score, then cosine) produced the OPPOSITE artifact: **1.4998**,
"Major Drift", with all three pairwise values ≈1.5. Z-scores are centered on
the corpus mean, so the three range-centroids must sum to ~zero — three
similar-sized groups are geometrically forced toward mutual ~120° angles
(cos 120° = −0.5 → distance 1.5) for ANY corpus, noise included. Cosine
measures deviation DIRECTION and is blind to deviation SIZE.

Final metric (ADR-003 amended, SPEC D-9): **RMS σ-shift** between
standardized centroids — "each feature moved X standard deviations on
average." Sanity triple: constant corpus → 0.0; strongly-drifted synthetic →
~2σ; the real corpus → **0.1405σ** (minimal drift — believable for a taste
map that's one coherent rock continuum with 9 all-three-ranges favorites).

**The realization:** journal #3 said "a distance metric is a claim about
which differences matter" — and both cosine failures were the SAME mistake
at different stages: measuring direction when the question was about
magnitude. Scale-invariance belongs in the preprocessing (z-scoring), not
in the metric. And instruments need sanity anchors at both ends: a
known-zero corpus and a known-large one would have caught both artifacts
before real data did.

> *Test a metric on a corpus with a known answer at each end of the scale.
> An instrument that has only ever seen one dataset hasn't been calibrated —
> it's been fitted.*

**Postscript (same day, P3):** the radar/heatmap had the VISUAL version of
the same bug — min-max normalization over 3 window-centroids pins every
axis to [0,1] *by construction*, rendering a 0.75% brightness shift as a
full-scale pinwheel divergence directly under a report saying "0.14σ,
remarkably stable." Both charts now normalize in σ units against the corpus
(`corpus_stats`), so visual divergence = effect size = the drift score's
units. One lesson, three costumes: metric, then centering, then normalization.

## Phase 5 — the agent layer

### 11. You can't denylist your way to a safe SQL tool (2026-07-03)

P5 exposes the warehouse to an agent via a `query_warehouse(sql)` MCP tool —
i.e. it executes model-written (and in P8, ultimately *stranger*-driven) SQL.
The instinct is a keyword denylist: block `DROP`, `INSERT`, `ATTACH`, … But
DuckDB's real danger surface isn't verbs, it's *functions* —
`read_csv('C:/…')`, `read_parquet`, `COPY … TO`, `INSTALL`, `glob` — and you
can't enumerate them all; the next release adds three more.

The fix was to stop guarding statements and start removing the capability:
load the gold Parquet into **native in-memory tables**, then
`SET enable_external_access=false` + `SET lock_configuration=true`. After that
the connection *physically cannot* touch the filesystem or network, install
extensions, or re-enable any of it — verified: a bare `read_csv` on the sealed
connection raises `PermissionException`, re-enabling raises
`InvalidInputException`. The DB is in-memory and ephemeral, so even a mutation
that slipped through would only scratch a throwaway copy. The SELECT-only
statement guard stayed — but demoted to defense-in-depth and a clear
read-only *contract* (nice errors for the agent), not the actual boundary.

**The realization:** this is journal #3 and #10's lesson wearing a security
hat — *know what your check actually does.* A denylist enumerates the bad and
hopes the list is complete; capability removal enumerates the *good* (query
these in-memory tables, nothing else) and makes completeness the default. The
test that proves it isn't "does it reject DROP" — it's "bypass the guard
entirely and confirm the sandbox still refuses to read a file."

> *Prefer removing a capability to blocklisting its uses. A denylist is only
> as good as your imagination; a capability you didn't grant can't be abused.*
