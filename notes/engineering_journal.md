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

*(entries land here once the pipeline runs for real)*
