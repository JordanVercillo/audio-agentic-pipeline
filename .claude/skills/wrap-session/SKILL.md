---
name: wrap-session
description: Save this session into the repo's durable memory (PROJECT_CONTEXT + journal + chronicle) and push it. TRIGGER when Jordan says "wrap up", "end session", "save context", or meaningful work happened and you're closing out. SKIP mid-pipeline-partner-session — its Phase 5 already wraps — and skip if nothing durable changed.
user-invocable: true
allowed-tools: [Read, Edit, Write, Bash]
---

Distill THIS conversation into the repo's living memory — a map, not a
transcript. Match the house style already in these files; don't reformat them.

## 1 — Recall
Re-read the conversation. Identify: decisions made, work completed **with
evidence** (pytest counts, commit hashes, audit results — a change without
evidence isn't done), genuine surprises, and the agreed next step.

## 2 — Update `notes/PROJECT_CONTEXT.md` (the hub)
- Rewrite **Status** + the single **➡️ NEXT ACTION** in place — don't append forever.
- Add any new key files / conventions to the §1 map.
- Append ONE dated **Session-log** line ending "**Left off:** …".
- Fix any fact this session proved stale (fix on sight — journals #4 / #14).

## 3 — Journal the surprises only
Genuine surprises → append a numbered entry to `notes/engineering_journal.md`
(situation → **The realization:** → a `>` takeaway). Routine progress is NOT a
lesson — most sessions add zero or one.

## 4 — Roadmap + chronicle
Tick anything completed in `notes/project_roadmap.md`. If the build **arc**
moved (an epic done, a direction set), add/adjust a row in
`docs/SESSION_CHRONICLE.md`.

## 5 — Verify before you claim
Never write "green" you didn't see. Run the relevant deterministic check and
record the real result: `uv run .claude/skills/warehouse-audit/audit_warehouse.py`
(data), `uv run .claude/skills/app-verify/verify_app.py` (live system), or
`pytest src/ -q`. (Locally the RAG-fallback tests may fail only because `.env`
points `WEBAPP_LLM_MODEL` at live Ollama — the CI way is `WEBAPP_LLM_MODEL=claude-opus-4-8`.)

## 5b — Scorecard (the cheap director pass)

`uv run python scripts/session_scorecard.py --base <the commit this session
started from> --session <N>`. Paste the row into `docs/QUALITY_LEDGER.md` and
fill the six defect-discovery lines by hand — they are the honest half, and the
row being visibly empty when skipped is the only thing that makes them real.

**Then check the FULL triggers** in `.claude/skills/director-review/SKILL.md`:
an epic/vision closing · an irreversible or public step · a new
security-adversarial surface · two consecutive sessions where D-use beat
D-self · every 10 sessions. **If one fired, stop and run `/director-review
--full` BEFORE committing** — the 2026-07-31 review found three blockers in a
day's work that every existing gate had passed, one of them corrupting live
serving data.

## 5c — Refresh the public numbers

`uv run python scripts/docs_facts.py --apply` — regenerates every countable
claim in `README.md` + `docs/CASE_STUDY.md` from the live system.

Do this EVERY wrap, not when you remember. `src/store/test_docs_freshness.py`
fails the build when a doc disagrees with the source, so skipping it turns a
one-command refresh into a red CI run. The test count moves whenever you add a
test — which is most sessions.

Numbers are REGENERATED, never retyped. Retyping is what produced ten wrong
numbers on the public README by 2026-07-31 (journal #60: a fix that is a
command, not a trigger, regresses on schedule). If a claim can't be derived,
`docs_facts.py` doesn't enforce it — and that's a hint the claim doesn't belong
in the docs either.

## 5d — Keep the plain-language explainer true

`docs/HOW_IT_WORKS.md` + `docs/concepts/` are the front door for someone with
little data-engineering background. Step 5c regenerates their NUMBERS; their
PROSE is on you.

Update it when this session changed **what the system does or how it behaves** —
a new stage, a changed default, a retired capability, a new honest limitation.
Do NOT update it for an internal refactor a reader would never notice; this set
explains behaviour, not implementation.

`src/store/test_docs_structure.py` fails the build on an orphan page or a dead
link, so a new concept page must be linked from the front door (or from the
page it follows).

## 6 — Commit + push (the repo is its own backup)
`git add notes/ docs/ && git commit -m "wrap-session: <one-line>" && git push`.
Watch CI stays green.

## 7 — Reply with only
The session-log line, the ➡️ NEXT ACTION, and any journal entry added. Nothing else.
