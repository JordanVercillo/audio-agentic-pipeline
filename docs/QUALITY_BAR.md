# The quality bar — what "production quality" means in this repo

Established by the **director review of 2026-07-30** (sessions 68–71, Vision F
S1–S6). "Production quality" is not testable as a phrase, so it is *defined*
here as the conjunction of Q1–Q12. Each standard is drawn from something this
repo already does well and turned into a thing that **fails**, not a thing we
intend.

The honest status column is the point. A bar every row passes on the day it is
written is a bar written to be passed.

| # | Standard | Mechanically checked by | A violation looks like | Status |
|---|---|---|---|---|
| **Q1** | **Every audit flag is PROVEN to fire.** A flag nobody has fired is documentation, not protection (journal #44). | `src/store/test_audit_tripwires.py` — set-equality over every flag name found in the audit SOURCE, plus a False-fixture and a True-fixture per covered flag. | A 26th flag ships green and silent forever. | ⚠️ **PARTIAL** — 14 of 25 covered; 11 named as debt in `_FIRE_UNTESTED`, a list that may only shrink. |
| **Q2** | **Enumerable surfaces assert set EQUALITY, never a sample.** | `test_route_matrix.py` (29 routes × 4 personas), `test_audit_tripwires.py` (flags), `test_feature_doc.py` (the 83 features, both directions). | A new route/flag/feature exists with zero assertions and the suite is green. | ✅ routes, flags, features · ❌ marts, `_ADDED_COLUMNS` |
| **Q3** | **Perf guards assert WORK DONE, not milliseconds.** | `src/store/test_store_perf.py` — SQL-shape tripwires, amortisation, constant query count, staleness edges. | `select(TrackFeatures)` on a request path; a session per row in a loop. | ✅ for library/analytics/similar/perceptual · ❌ not yet extended to the S5 artist readers |
| **Q4** | **Payload is bounded by the page, not the corpus** — and the tail stays reachable. | Paired tests: bounded AND `page_links` always reaches the last page. | A template loops the whole corpus into one document. | ✅ /library · ⚠️ /artists, /recommend, /explore bounded in S6 but without the paired tail test |
| **Q5** | **A rendered number is DERIVED from what rendered**, never recomputed beside it (journal #27/#60). | `assert caption_number == body.count(<element>)`. | "Every cached song" while plotting 37% of it. | ⚠️ asserted on /analytics; not systematic |
| **Q6** | **New code is covered, and the floor only ratchets up.** A test COUNT is not a quality signal. | `pytest --cov=src` in CI + `scripts/coverage_summary.py`. | 910 tests and an untested new module. | ❌ **UNMEASURED until the next CI run.** Coverage cannot run on Windows (numpy C-extension clash with the tracer) — CI is the oracle. **No threshold until the baseline is known**; a number guessed first is theatre. |
| **Q7** | **Tests are synthetic and machine-independent.** | Ground rule 5 · `src/conftest.py`'s autouse neutralising of all live-model env routes (journal #34) · CI as the oracle (journal #55). | Green locally, red on CI — or green on both for the wrong reason. | ⚠️ held by discipline; not mechanically enforced |
| **Q8** | **Anti-vacuity: every gate has a control that FLIPS.** A test that cannot fail is decoration. | `test_every_forbidden_marker_is_required_somewhere`, `test_owner_gate_fails_closed_without_env`, and the both-directions rule in Q1. | 40 `forbid` assertions made tautological by a template rename. | ✅ routes — the best-in-repo example |
| **Q9** | **No claim without a before/after measurement**, and the fault's measured cost lives in the guard's docstring. | The scorecard's `measured claims` field; `test_store_perf.py`'s header is the template. | "Made it faster." | ✅ culturally (S1, S3, S6) — now a required scorecard field |
| **Q10** | **Absent-safe and fail-closed.** Optional data renders honestly when missing; a gate with no env is shut. | A field-absent test per optional datum; the D-57 withhold; the owner-gate control. | `nan` truthy in an `<img src>` (journal #30). | ✅ well established |
| **Q11** | **Untrusted text is inert.** Import names, playlist/album/YouTube titles and LLM output never render `\|safe`, never reach a prompt un-neutralised; URLs are scheme-guarded. | Per-instance XSS regressions + INJ-PI. **Missing:** an allowlist test over `\|safe` occurrences in `templates/`. | A new template pastes an artist name with `\|safe`. | ⚠️ per-instance only |
| **Q12** | **Shipped ≠ done.** Done = suite green (CI-equivalent) + warehouse-audit + qa_audit + smoke/app-verify + a live browser check for UI + memory updated. | The five evidence lines in the scorecard; `/wrap-session` refuses "done" without them. | "It ran." | ✅ in practice · ❌ not mechanised |

## How to use this

- **Every session** runs the cheap pass (`/director-review`, or its step inside
  `/wrap-session`) and appends one row to `docs/QUALITY_LEDGER.md`.
- **A full review** runs on a named trigger, not a schedule — see the skill.
- A standard is only worth adding here if you can name **the test that fails**
  when it is violated. "We should be careful about X" belongs in a charter, not
  in this table.

## The four that convert real risk into a failing test

Q1, Q2, Q6 and Q11. The others are largely already held by habit; these four are
where habit has already proven insufficient — every one of them corresponds to a
defect this project actually shipped.
