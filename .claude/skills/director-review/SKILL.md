---
name: director-review
description: Strict evaluation of what a session actually shipped — run the existing gates, score the session against docs/QUALITY_BAR.md, and (on a named trigger) red-team the slice with independent experts. TRIGGER on "/director-review", "review what we shipped", "is this production quality", at an epic/vision close, or before an irreversible or public step. SKIP for a routine slice — the CHEAP pass runs inside /wrap-session automatically.
---

# Director review

Two modes. **Most sessions never pay for the full one.** The cheap pass is
mechanical and runs every wrap; the full pass is expensive and fires on a named
trigger, never on a schedule.

The standards live in [`docs/QUALITY_BAR.md`](../../../docs/QUALITY_BAR.md)
(Q1–Q12). "Production quality" is not a testable phrase; it is *defined* as the
conjunction of those twelve, each of which names the test that fails.

---

## CHEAP — `--scorecard` (every wrap, ~2 min, no judgment)

1. **Run the gates that already exist.** `pytest src/ -q` ·
   `ruff check` · `uv run .claude/skills/warehouse-audit/audit_warehouse.py` ·
   `uv run python scripts/qa_audit.py` · `scripts/smoke_public.py` if the app
   is up.
2. **Score the diff:** `uv run python scripts/session_scorecard.py --base <the
   commit the session started from> --session <N>`.
3. **Fill the six hand lines** — the defect-discovery channels. They are a
   discipline, not a gate; the row being visibly empty when skipped is the only
   thing that makes them real.
4. **Append one row** to `docs/QUALITY_LEDGER.md`. Two lines maximum per
   session — it must not become a second PROJECT_CONTEXT.
5. **Check the FULL triggers below.** If one fired, say so and stop.

It asserts nothing new. The "did you forget a gate" work belongs inside pytest
(Q1/Q2 set-equality), where it fails a build instead of a report.

---

## FULL — `--full` (a trigger fired, not a schedule)

**Triggers.** Any one:
1. An epic or vision closes.
2. Before an irreversible or public step (a history scrub, a force-push, a
   corpus-scale data program, a public flip).
3. A new security-adversarial surface (auth, gates, untrusted text, tool use,
   uploads).
4. Ledger drift: escape rate up, **or two consecutive sessions where D-use
   exceeds D-self**.
5. A floor of every 10 sessions.

**Order.**
1. The cheap pass.
2. **Independent red-teams, in parallel** — one per domain the session touched
   (`webapp-expert`, `data-platform-expert`, `dsp-expert`, `llm-rag-expert`).
   Give each the commit range and instruct it to be **hostile**: the author
   already self-reviewed, and that is the weakest kind of review. Ask for
   findings ranked BLOCKER/HIGH/MEDIUM/LOW with `file:line`, a concrete failure
   scenario, and a proposed fix or test. Tell them **not to edit files**.
3. **Verify every BLOCKER yourself before acting.** A claim about live data is
   a claim until you reproduce it.
4. **Fix the blockers**, each with the tripwire that would have caught it.
5. Score the twelve standards; record which PASS, PARTIAL, FAIL.
6. Write `docs/reviews/YYYY-MM-DD_director-review_<scope>.md`: verdict, what
   broke (with discovery channel and pre-existing yes/no), what improved
   (before → after, and the command that measured it), actions taken, and
   **what is carried, not fixed**.
7. Only the ledger row and the blocker count go into the ledger.

**Escalate, never self-apply:** any repair that mutates the live serving plane
(cluster identities, quarantines, corpus-scale rewrites). Back up first, state
the blast radius, and let the owner decide — the
[`CORPUS_MIGRATION_PLAYBOOK`](../../../docs/CORPUS_MIGRATION_PLAYBOOK.md) owns
that shape.

---

## The disciplines that make this worth running

- **Measure before claiming.** Every "improved" number needs the command that
  produced both halves (Q9).
- **A test named for an invariant is not a test of that invariant.** The 2026-07-31
  review's blocker sat under a test called
  `test_promotion_remap_preserves_cluster_identity` that checked one of the
  invariant's two halves.
- **Verify a red-team's claims.** They are usually right and occasionally
  wrong; reproducing takes a minute and the fix takes an hour.
- **Count discovery channels honestly.** A low `D-self` is not an insult, it is
  the signal that the gates are pointed elsewhere.
- **Carry what you don't fix, in writing.** A review whose findings evaporate is
  a review that taught nothing.
