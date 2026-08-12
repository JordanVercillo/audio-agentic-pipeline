# Quality ledger

One row per session. Two lines maximum — full reviews live in `docs/reviews/`.
Produced by `scripts/session_scorecard.py` (mechanical half) plus the
defect-discovery channels (hand-entered — a discipline, not a gate; see
`docs/QUALITY_BAR.md`).

**The four derived numbers that matter**

- **Escape rate** = D-post ÷ total — the only one a user feels.
- **Self-catch ratio** = (D-self + D-matrix) ÷ total — rising means the gates
  are doing the work.
- **Debt ratio** = pre-existing ÷ total — high means building on top is your
  best bug detector, which is a finding, not a compliment.
- **Tripwire density** = tripwires added ÷ slices.

| session | date | slices | commits | tests | ruff | audits | code/test lines | defects (self·matrix·build·use·red·post) | notes |
|---|---|---|---|---|---|---|---|---|---|
| 68–71 | 2026-07-29/31 | Vision F S1–S6 | 17 | 905→914 | clean | all-false | +1722/+1069 | 1·3·3·2·**3**·0 | Full review: `reviews/2026-07-31_director-review_vision-F.md`. **3 BLOCKERS found by red-team**, 1 corrupting live serving data for 24 h. Self-catch 33%. |
| 72 | 2026-07-31 | carried findings (12/12) + consolidation | 20 | 914→948 | clean | all-false (26 flags) | +873/+1287 | 3·2·0·**5**·1·0 | All 12 carried findings closed. New tripwire `CLUSTER_ASSIGNMENT_DESYNC` proven to fire. Percentile error 4.69→0.72 pts. D-74 declines P4.6.5 on a measured premise. FAISS stack deleted (`docs/DELETIONS.md`). Public numbers + docs structure now self-checking. **D-use beat D-self 5:3 — if session 73 repeats it, the FULL review trigger fires.** |
| 73 | 2026-08-12 | Track B - measure the models | 8 | 948->971 | clean | all-false (26 flags) | +1055/+460 | 2.1.0.0.2.0 | First offline eval for both shipped models. Whitening SHIPPED (+0.0059 held out). Feature selection REJECTED (+14% pool / **-11.3% untouched holdout**). Two of my own earlier readings corrected by measurement. |
| 74 | 2026-08-12 | goal reframe - the workplace demo | 3 | 975->986 | clean | all-false (26 flags) | +317/+98 | 0.2.0.0.3.0 | D-75 declines Phase 5 + the ML track. Three consults all found the blocker was DISCOVERABILITY, not capability. /eras built from a stored-but-unread column: +4.1 dB loudness, -66 s length across 6 decades. |
| 75 | 2026-08-12 | fact_section + the Phase 2 roadmap | 3 | 986->996 | clean | all-false (26 flags) | +145/+156 | 1.0.1.0.0.0 | Second fact grain shipped (65.1% of tracks change key mid-song). Found a NaN crash in LAST session's code that took down the whole mart rebuild. Build backlog now empty by design. |

## Reading the rows

Sessions 68–71 shipped a lot and shipped three blockers. Every gate the project
owns read green throughout; none was pointed at the invariant that broke. The
cheapest thing that found real defects was **someone other than the author
looking**.

### Session 72 — what the fix-up round itself taught

Test-to-code ratio inverted (1.39 test lines per code line, against 0.62 for the
arc being fixed) — expected, because closing a review finding IS mostly writing
the assertion that was missing.

The two defects this round produced were both found by loading the page. One of
them — `artist_drift` pointed at a column the album builder does not compute —
had **930 passing tests over it**, every one supplying its own column
explicitly, while the surface rendered nothing at all. A test that constructs
its own inputs cannot notice that production supplies different ones.

> D-use caught 2 of 2 this round. It remains the cheapest channel the project
> has, and the only one that sees a blank page as blank.

### Session 72 — the channel that keeps winning

D-use caught five defects; the author's own tests caught three. Two of the five
were invisible to a 930-test suite for structural reasons worth naming:

- **`artist_drift` rendered nothing at all** after its column moved to one the
  album builder doesn't compute. Every test passed its own column explicitly,
  so all of them stayed green while the surface went blank. *A test that
  constructs its own inputs cannot notice that production supplies different
  ones.*
- **The live app served stale code for a day** (journal #68) because every
  health indicator reported liveness and none reported version.

Both fixes were the same shape: make the missing comparison exist as an
assertion. The default column must be in `_ALBUM_FEATURES`; the running commit
must equal HEAD.

**Full-review trigger check:** the FAISS deletion is public but recoverable via
a logged one-line `git checkout`, not a history scrub or force-push, and a full
review had already run on this session's code the same day — so no second full
pass. Recorded rather than assumed. The D-use/D-self ratio is the one to watch.

### Session 73 - the channel that mattered was the holdout

D-self 2 (the nested holdout caught the feature-selection overfit; the
perfect-retriever control proved the harness could score 1.0). D-red 2 (the
research consult confirmed MPD's licence and surfaced ListenBrainz; the
data-platform consult found the 39% MPD blind spot and the `canonical_ids()`
foot-gun). D-use 0 - this session barely touched the UI.

The number worth carrying: **two of my own stated conclusions were reversed by
measurement in the same session I stated them** - "k=2 may be an artifact" (it
is not) and "the model loses to popularity" (it wins 7x where it matters).
Both were reasonable readings of real numbers. Neither survived being tested.

Also: one commit was pushed with a red test in it. I ran the suite, saw the
failure in the output, and committed anyway. Caught and fixed in the next
commit, but the discipline failed before the tooling did.

### Session 74 - the gates all start from a URL you already know

D-red 3: every finding came from the consults, and each was verified before
acting. D-matrix 2: the route matrix demanded a row for each new route the
moment it was registered - the standing gate working exactly as designed,
twice. D-self 0, D-use 0.

That D-self 0 is the entry worth reading. The defects were not code defects:
a landing page whose primary button no visitor could use, a nav of two links,
the best artifact on the site three clicks deep. **986 tests, 26 audit flags
and a route x persona matrix pass over all of it**, because every gate this
project owns begins from a route someone already knew existed (journal #72).

One consult claim was REJECTED after checking: '77 vs 83 is a stale
contradiction'. Both numbers are real and different - the frozen similarity
vector and the exposed feature count - and bulk-replacing would have
introduced an error rather than fixed one.

### Session 75 - D-build, and what a passing suite did not know

D-self 1 (the section-mart guards), D-build 1 - and the D-build one is the
entry worth keeping. Building `fact_section` crashed `rebuild_marts()` on a
line shipped LAST session: `None if y is None` against a pandas float64
column, where every None is NaN and `NaN is None` is False.

986 tests, a green CI and a rendered /eras page had all agreed that code was
correct, because none of them had ever been handed a track without a release
date. The defect was unreachable until the data changed, and then it took
down every mart at once rather than degrading (journal #74).

Test-to-code ratio 1.08 - the highest of any build session, because most of
the work was guards on a new grain rather than new surface.
