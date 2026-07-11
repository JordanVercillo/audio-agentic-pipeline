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

## Phase 7 — the scale slice

### 12. "It ran on my machine" — because my machine wasn't the machine (2026-07-04)

P7's whole point is a *proof*: `spark/parity_check.py` runs the real Spark
engine and asserts its dedup row-counts and centroids match the pandas
transforms. I probed it locally first — `Spark 3.5.6 session up`, imports
clean — and shipped the CI job pinned to **Java 11** ("Spark 3.5 runtime,"
I reasoned). CI went red instantly: `UnsupportedClassVersionError … class
file version 61.0, this Java only recognizes up to 55.0`. 61 = Java 17,
55 = Java 11. The JVM gateway died before a single assertion ran.

The tell was in the lockfile: `py4j 0.10.9.9` — the bridge that ships with
**PySpark 4.x**, not 3.5 (which pins 0.10.9.7). `uv sync --frozen` had
resolved `pyspark>=3.5.0` all the way to **4.1.2**, whose jars are Java-17
bytecode and which *dropped Java 8/11 entirely*. So why did my local probe say
"3.5.6"? Because I ran it with the **anaconda** Python — which has its own
conda-installed pyspark 3.5.6 and my system Java 11 — not the **uv `.venv`**
that CI builds from the lock. Two different Sparks on two different Javas; the
one I tested was not the one I shipped. Bumping the CI job to Temurin 17 turned
it green: `dedup 30=30`, `dedup 90=90`, `centroid parity within 1e-3`.

**The realization:** "works locally" is only evidence about the environment
you actually ran in — and a convenient interpreter on `PATH` is rarely that
environment. The reproducible truth is the *frozen* install (`uv sync
--frozen`), and the place it gets exercised is CI. This is why P6's CI job
exists at all: not to run tests I've already run, but to run them in the
environment the lockfile *promises*, on a box that shares nothing with mine.
The version floor (`>=3.5.0`) and the resolved pin (`4.1.2`) are different
facts; only the lock knows the second one, and only CI runs it.

> *Test the environment you ship, not the one that's convenient. If it didn't
> run from the frozen lock, "it ran" is a statement about your PATH, not your
> code.*

## Epic C — population clustering

### 13. One ghost track poisoned every feature column (2026-07-07)

First real-data training run: "skipped (not enough cached tracks)" — on a cache
holding 118 tracks. The debugger said `all_features()` returned all 118. The
culprit was the ONE track whose audio was never acquired (the audit's known
soft warning): its feature dict is all-None, and `select_feature_cols` required
a column to be present in EVERY row. One sparse row → zero usable columns →
training silently declined. Synthetic tests never caught it because synthetic
corpora are, by construction, complete.

**The realization:** intersection semantics are brittle exactly where real data
lives — the requirement isn't "present everywhere," it's "present enough to
train on." Coverage (≥90% of rows) + excluding incomplete rows from the run is
the honest version: the ghost sits out and gets assigned when its features
arrive, instead of vetoing the population.

> *Never let one degenerate row define the schema. Select columns by coverage,
> filter rows by completeness — and keep one deliberately-sparse row in the
> test fixtures, because synthetic data is too polite to break you.*

## Epic E — go-live

### 14. The DNS pages looked healthy for a zone that didn't exist (2026-07-08)

Pre-cutover check of the domain's records: Squarespace's DNS page listed a
complete, correct-looking zone (MX, SPF, DKIM, A records). But Cloudflare's
import found 0 records — and querying the four delegated
`ns-cloud-d*.googledomains.com` servers directly returned REFUSED on every
record type. The Google Cloud DNS zone behind the delegation had been deleted
(likely in the Google Domains → Squarespace shuffle); the domain — and its
email — had been silently dark for an unknown while. Squarespace's page was
an inactive *copy*, faithfully displaying records nobody was serving.

**The realization:** a DNS control panel shows configuration, not reality —
the same docs-fiction pattern as journal #4, one layer down the stack. The
registrar's page, the old host's page, and the live answers are three
different things; only `Resolve-DnsName <domain> -Server <the actual
delegated NS>` is ground truth. The "risky" migration was actually the
repair, and five minutes of authoritative queries flipped the plan from
"carefully preserve email" to "restore email, fast."

> *Before migrating DNS, query the delegated nameservers directly. A record
> shown on a web page is a claim; a record served by the authoritative NS is
> a fact.*

### 15. The PR merged early, and `git branch -d` covered for it (2026-07-08)

"Merge PR #7 and stop the app" — but PR #7 turned out to have been merged the
day before, minutes after it was opened at the Epic-B point. Every commit
pushed to the branch afterwards (APP_SPEC v2, Epics C, D, E, the go-live) kept
updating a PR that was already closed. Then the tidy-up deleted the branch —
and `git branch -d`, which is supposed to refuse unmerged work, allowed it:
its rule is "merged into the UPSTREAM if one is set," and the local branch
exactly matched origin/epic-a/feature-cache, so git called it merged. One
`git push --delete` later, eight commits had no ref on the remote. Recovery
was calm because the objects still existed locally (the tip hash was in the
session transcript): restore branch at the hash → PR #8 → merge → verify.

**The realization:** two safety rails failed in the same direction — the PR's
"merged" state said nothing about WHICH commits it merged, and -d's merged
check compared against the wrong base. The habit that actually saved it:
verifying main's CONTENT (grep for v2 markers, --loop, file existence) instead
of trusting the merge commit's existence.

> *"Merged" is a property of a commit range, not a PR. After any merge, verify
> the content landed — and never trust `-d` on a branch with an upstream.*

## Post-launch — the new-user pipeline hardening

### 16. The audit checked everything except the queue's consumer (2026-07-09)

"How do we ensure new users get their songs extracted?" The mechanism already
worked — a tester's uncached track went queued→done in 52 seconds the night
before. But the app-verify skill, built to end doc-fiction, had flags for the
webapp, the tunnel, the cache, the marts, the evals… and none for the worker.
The one process whose death breaks the product's core promise — invisibly,
since queued jobs just sit — was the one process nothing watched. The fix
(heartbeat row + WORKER_DOWN/QUEUE_STUCK) flagged its own blind spot on first
run: the live worker read DOWN because it was running pre-heartbeat code.
Bonus orphan found while reading the state machine: a worker crash mid-job
leaves the claim 'running' forever, and enqueue() politely refuses to requeue
a "live" job — so one crash could permanently strand a track.

**The realization:** liveness checks accrete around what has VISIBLY failed
before (the tunnel, DNS). Async workers fail invisibly by design — the queue
absorbs the silence. Enumerate the processes the product's promise depends
on and give each one a heartbeat the auditor can see; then check the state
machine for states only a living process can exit.

> *A queue without a monitored consumer is a promise nobody is keeping. Audit
> every process the product depends on — and every job state that needs a
> living process to leave it.*

### 17. The seeded ghost got a second life across a semantic boundary (2026-07-09)

The cache held 119 "tracks" but only 118 were real: the warehouse's one
metadata-only row (the known soft warning; the same ghost as #13) had been
seeded into the feature cache with all-None features. In the warehouse that
row means "not yet downloaded" — a fact with a workflow. In the cache,
presence means "analyzed": the dashboard showed it done (all "—"), and
because cached ids are never re-enqueued, the queue could never repair it.
The seed had faithfully copied a row whose MEANING didn't survive the copy.
Fix: seed keeps the meta (the worker can search for it later) but skips the
feature upsert; the live ghost row was deleted, so the next visitor who has
the song triggers a real extraction.

**The realization:** #13 fixed the ghost's effect on clustering and F1 excluded
it from perceptual — every CONSUMER learned to step around it, while the
PRODUCER kept minting it. When data crosses a system boundary, the invariant
to preserve is the receiving system's semantics ("row exists ⇒ analyzed"),
not the sending system's shape.

> *At a system boundary, copy meanings, not rows. If presence implies a
> promise in the target system, the loader must enforce the promise — and
> fix the producer, not just every consumer.*

## Epic F-v2 — frame-level audio

### 18. create_all builds tables, never evolves them (2026-07-09)

F-v2a added a `loudness_curve` column to the `track_features` model. Every test
passed (temp DBs are built fresh by `Base.metadata.create_all`, which emits the
full current schema) — then the backfill hit the LIVE cache and threw
`no such column: track_features.loudness_curve`. `create_all` only issues
`CREATE TABLE IF NOT EXISTS`; against a table that already exists it does
*nothing*, so a column added to the model never reaches a database created
before it. The green suite hid it precisely because tests never carry a schema
forward — they start from zero every time.

**The realization:** the test path and the production path exercise different
schema lifecycles. Fresh-create (tests) and evolve-in-place (the running cache)
are not the same code, and only one of them was covered. The fix is a tiny
forward-only migration on init — inspect the live columns, `ALTER TABLE ADD
COLUMN` the missing ones (idempotent, NULL for old rows, online on both SQLite
and Postgres) — so the persistent DB self-heals the moment new code opens it.

> *A green suite proves your CREATE path, not your ALTER path. If a long-lived
> DB outlives the schema, add columns with an idempotent migration on startup —
> `create_all` will silently skip them on a table that already exists.*

### 19. The backbeat masquerades as 2/4 (2026-07-09)

F-v2b's meter estimator autocorrelates beat accents: the lag whose accents best
repeat is the bar length. On the first real-corpus backfill it labeled **42 of
117 tracks as 2/4** — impossible for a rock/alt corpus that's overwhelmingly
4/4. The cause is musical, not a bug: a 4/4 song with a backbeat accents beats 1
AND 3, which is a period-2 pattern, so lag-2 autocorrelation ties or beats
lag-4. Worse, 2/4 and 4/4 are genuinely the same accent periodicity counted at
different levels — no accent-only method can separate them, and real 2/4 is
vanishingly rare. The synthetic tests couldn't catch it: a hand-built period-4
accent pattern has no backbeat, so it cleanly returned 4.

**The realization:** the fix wasn't a better algorithm, it was a narrower,
honest claim. Dropping 2 from the candidate set (duple → the 4 default) makes
the estimator answer the question it can actually answer — "is this an
odd/compound meter (3, 5, 6, 7), or duple?" — instead of pretending to
resolve an ambiguity that doesn't exist in the signal. The distribution went
from absurd (2/4×42) to credible (4/4×83, 3/4×17, a few odd). Same tier-honesty
discipline as F1's instrumentalness deferral: when the data can't support the
fine distinction, report the coarse one and say so in the feature's own words.

> *When an estimate is surprising on real data, ask whether the signal can even
> support the distinction before "fixing" the model. Sometimes honesty means
> collapsing two indistinguishable answers into one and narrowing the claim —
> and only real data, not synthetic fixtures, reveals which distinctions are
> real.*

### 20. Our own guardrail was the stale claim (2026-07-09)

Planning the audio-feature roadmap, Jordan asked whether we could pull Spotify's
`popularity` directly. Rule 3 of CLAUDE.md and `.agent_prompts/01` both state it
flatly: "popularity has been removed from Track/Artist response objects" — and
`fetchers.strip_deprecated_fields` actively deletes it on every fetch. But a
live check of `GET /tracks` shows `popularity` is still returned, labelled
**Deprecated** — present, described, discouraged, not gone. Our guardrail had
hardened an early defensive assumption into a stated fact, and every fetch since
had been throwing away real, available data on the strength of it.

**The realization:** journal #14 was about trusting a DNS control panel over the
authoritative answer — a stranger's doc. This is the same failure one layer in:
*our own* doc was the claim, and we'd been coding against it for months. A
guardrail that over-restricts is invisible — nothing errors, you just quietly
never see the data — which is exactly why it survived. The fix isn't just
un-stripping the field; it's holding project doctrine to the same "verify
against reality" bar we hold external docs to, and re-checking load-bearing
"it's gone / it can't / never do X" assertions against the live system now and
then. (Boundary kept: popularity is *fetched context*, never an ML input —
Spotify's terms forbid training on their content.)

> *Audit your own guardrails against reality, not just other people's docs. A
> rule that says "X is impossible" quietly costs you X forever if X quietly
> became possible — over-restriction fails silently, so re-verify the
> load-bearing "nevers."*

### 21. The fade-out/fade-in asymmetry was the honesty check (2026-07-09)

F-v2c detects fades by thresholding the stored loudness curve. The first cut —
"the edge sits a bit below the sustained level" — flagged **60% fade-ins**,
which is absurd for a rock corpus (true production fade-ins are ~10%). Nothing
errored; the number was just wrong, and a synthetic test with a clean fade curve
happily passed it. What exposed it was a *musical prior*: real fade-ins are rare,
fade-outs are common, so a detector reporting them roughly equal is catching
something else — here, quiet intros (soft openings that aren't production
fades). Adding a depth gate (the edge must sit ≥20 dB below full — a fade FROM
SILENCE, not a merely-soft start) pulled it to fade-in 19% / fade-out 34%, and
the fact that fade-out now exceeded fade-in was the signal the detector had
become honest. (The beat grid hit the twin of #19's density problem: a full
beat grid is ~1px/beat — a solid smear — so it draws bars, every meter-th real
beat, spacing honest and phase approximate.)

**The realization:** a detector's *output distribution*, checked against a
domain prior, is a validation instrument that unit tests can't be — tests prove
the code does what you wrote; only real data against "what should the world look
like?" reveals that what you wrote was the wrong thing. When a new feature lands,
look at the shape of what it produces across the whole corpus, and ask whether a
domain expert would find that shape believable.

> *Validate a new estimator by its distribution against a domain prior, not just
> by unit tests. "Does the mix of answers look like the world?" catches wrong-
> definition bugs that green tests sail right past — and a known asymmetry
> (fade-outs beat fade-ins) is a free correctness check.*

## Whole-application review

### 22. The strategic review predicted where the code bugs would be (2026-07-09)

A full-app audit run as three parallel streams: two cold review subagents (one
on the webapp security surface, one on the data-layer robustness) plus my own
architecture/strategy pass. Before either agent reported, the strategic pass had
already named the top fragility: "yt-dlp match-blindness + the queue are the
biggest data-quality/availability holes." Both agents came back and the two HIGH
findings were exactly that — a permanently-unfetchable track hot-looping because
`enqueue` reset the attempt counter (no dead-letter), and the worker `--loop`
crashing the only consumer on a transient DB error. The security surface, by
contrast, came back clean everywhere the design had been deliberate (PKCE state,
the DuckDB capability-sandbox, the ytsearch prefix, session signing) with one
real defect where a hand-built string bypassed the framework's default
protection (SVG `<title>` interpolation skipping Jinja autoescape).

**The realization:** bugs cluster where the architecture is *thin*, not
randomly — the places you'd point to as "the risky part" on a whiteboard are
where the confirmed defects actually live, and the places the framework or a
deliberate design decision covers (autoescape, parameterized SQL, capability
removal) stay clean. That means a strategic "where is this thin?" pass is a
real triage instrument, not hand-waving: it tells you where to aim the expensive
deep review. And fanning the deep review out to parallel agents while holding
the synthesis yourself — verifying each confirmed finding by hand before
touching code (the one XSS sink, read and reproduced, before escaping) — kept
the fix set precise: 7 real fixes, zero speculative churn, one clean pass.

> *Bugs pool where the architecture is thin — so a "where is this fragile?"
> strategic pass predicts the deep review's findings and tells you where to aim
> it. Fan the search out; keep the synthesis and the verify-before-fix yourself.*

### 23. The lock's first victim was its own successor (2026-07-10)

The single-instance worker lock (refuse to start when another pid's heartbeat
is fresh) worked perfectly on its first live test — a second manual worker
refused with a clear message. Then, planning the deploy, the footgun surfaced:
`app_control restart` stops the old worker and starts a new one within two
seconds, and the predecessor's heartbeat stays fresh for up to five minutes.
The new safety interlock would have blocked the app's own standard deployment
path — the very restart that ships the lock. The fix wasn't weakening the lock
but recognizing there are two kinds of caller: the MANAGED lifecycle (which
just killed the predecessor and has its own double-start guard) passes
--takeover; the manual path stays fully locked.

**The realization:** an interlock is designed against the adversarial case (a
human absent-mindedly starting a second worker) and then meets the routine case
(the system replacing itself). Every guard that says "refuse if X looks alive"
needs an answer to "who legitimately replaces X, and how do they prove it?" —
otherwise the first thing it blocks is its own rollout.

> *Test a new safety interlock against the system's own lifecycle, not just
> the threat it was built for. Supervised restarts are the most common
> "second instance" — give the supervisor an explicit takeover path instead
> of teaching operators to bypass the lock.*

### 24. The detector was blind to the axis the structure lived on (2026-07-10)

F-v3's section detector passed its synthetic A–B–A test and produced a
credible corpus distribution after the fragmentation tuning — and then the
spot-check of NAMED songs caught what neither instrument could: Knights of
Cydonia, famously a six-minute suite of distinct parts, came back as ONE
366-second section. The cause was principled, not a bug: recurrence ran on
chroma (harmony), and KoC riffs around E throughout — harmonically static,
its structure lives in TIMBRE (harmonica → gallop → vocals). The detector
literally could not see the dimension the song's structure was on. Stacking
z-balanced chroma+MFCC into the recurrence fixed it (3 honest sections), and
the corpus distribution improved everywhere (single-section tracks 24→9).

**The realization:** three validation instruments, three different bugs.
Synthetic fixtures caught the merge/coverage logic; the corpus DISTRIBUTION
(#21) caught fragmentation and the A|A coalesce artifact; but only
spot-checking songs where I personally know the ground truth caught the
representation blindness — a detector can be well-behaved statistically while
measuring the wrong thing. Named examples with known answers are the
regression suite for meaning.

> *Validate on three levels: synthetic fixtures for logic, corpus
> distributions for statistical sanity, and a handful of NAMED examples whose
> ground truth you personally know for meaning. Each catches a class of bug
> the others structurally cannot.*

### 25. The eval we built in F0 stopped a vibes-based ship (2026-07-11)

A3 wired /ask + /classify to a local $0 model (gemma4:12b). The direct smoke
looked great — warm, grounded, well-cited prose — and it would have been easy
to ship on that impression. But the golden eval set from F0, built long before
any local model existed, graded it **5/15** against the deterministic template's
15/15: gemma4 was paraphrasing labels ("moderate drift" → "moderate shift") and
describing the vibe without NAMING the artist. Neither is a hallucination
(no_invention stayed 15/15) — they're grounding-precision gaps a single
impressive sample hides but 15 graded cases expose. Tightening the contract
(name real artists; reuse labelled results verbatim) recovered it to 9/15, and
the residual gap became an explicit, owner-made ship decision instead of a
silent default.

**The realization:** the value of an eval harness isn't the number, it's the
moment it contradicts your gut. The smoke said "ship it"; the eval said "it's
measurably looser than what you have." Both were true — the model IS nicer to
read AND does cite less precisely — and only the eval surfaced the second half,
turning a vibes call into a documented tradeoff the owner could actually weigh.
An eval you wrote before you had the thing under test is worth ten written to
rationalize it afterward.

> *Build the eval before the thing it judges, and believe it when it fights your
> first impression. A single good sample is an existence proof, not a
> distribution — the harness measures the distribution, which is what ships.*
