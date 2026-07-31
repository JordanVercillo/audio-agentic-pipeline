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

## Reading the first row

Sessions 68–71 shipped a lot and shipped three blockers. Every gate the project
owns read green throughout; none was pointed at the invariant that broke. The
cheapest thing that found real defects was **someone other than the author
looking**.
