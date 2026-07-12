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

## 6 — Commit + push (the repo is its own backup)
`git add notes/ docs/ && git commit -m "wrap-session: <one-line>" && git push`.
Watch CI stays green.

## 7 — Reply with only
The session-log line, the ➡️ NEXT ACTION, and any journal entry added. Nothing else.
