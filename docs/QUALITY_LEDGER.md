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
| 72 | 2026-07-31 | carried-findings fix-up (12/12) | 6 | 914→930 | clean | all-false (26 flags) | +318/+441 | 1·0·0·**2**·0·0 | All 12 carried findings closed. New tripwire `CLUSTER_ASSIGNMENT_DESYNC` proven to fire. Percentile error 4.69→0.72 pts. **Both new defects found by USING the page**, not by 929 tests. |

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
