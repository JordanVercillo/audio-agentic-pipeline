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
