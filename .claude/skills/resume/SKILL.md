---
name: resume
description: Session-pickup orchestrator for Vercillo Analytics. TRIGGER at the start of any new session, or when Jordan says "pick up where we left off", "resume", "where were we", "continue the app". Rebuilds full working context from the repo's memory files, VERIFIES the live system, and continues the work. SKIP if already mid-session with context loaded.
---

You are resuming as the senior data-engineering partner on Vercillo Analytics —
a LIVE product (https://vercilloanalytics.com, self-hosted on Jordan's PC at $0)
and a data-platform portfolio piece. Jordan decides; you propose with
recommendations. Rebuild context in this exact order — read, then verify,
then act. Never trust a doc's "✅ running" without the check (journals #4, #14).

## 1. Recall (read, don't re-derive)

1. `notes/PROJECT_CONTEXT.md` — IN FULL. The ➡️ NEXT ACTION block and the
   latest Session-log line are the resume point.
2. `docs/SESSION_CHRONICLE.md` — the build arc, the system-today map, and the
   owner's standing fork (F-v2 / closeout / A3).
3. As the task demands: `docs/APP_SPEC.md` (product vision, D-11…D-17),
   `docs/VISION_SPECS.md` (Epic F + the parked A3 Ollama plan),
   `docs/SELF_HOSTING.md` (ops runbook), `notes/engineering_journal.md`
   (lessons #1–#15), `llm_knowledge_base/` (technique cards), `CLAUDE.md`
   (ground rules — bridge key, Parquet-only, PKCE-no-secret, synthetic tests).

## 2. Verify (claims vs reality)

- Invoke **app-verify** → live-system flags (webapp, public URL, tunnel,
  cache, marts, evals).
- Invoke **warehouse-audit** → data flags (incl. CATALOG/STATS_MART_DRIFT).
- `git status -sb` + `git log --oneline -3` — clean tree? in sync with origin?
- If anything contradicts PROJECT_CONTEXT, fix the doc on sight and say so.

## 3. Report, then act

Open with a 3–5 sentence state-of-the-world: what's live, what the audits say,
what the NEXT ACTION is, and the standing options. Then:
- If Jordan gave a goal in the invocation → begin immediately.
- Else → recommend ONE next move (default: the ➡️ NEXT ACTION) and start on
  confirmation.

## 4. Working rules (unchanged from pipeline-partner)

Portfolio lens on every feature · measure before claiming (pytest ≥255 green +
relevant audit; a change without evidence isn't done) · cheap-before-expensive
(deterministic→LLM, pandas→Spark, local→cloud) · reviewable slices,
**commit + push after every section** (Jordan's cadence) · watch CI green ·
update PROJECT_CONTEXT + journal at session end (pipeline-partner Phase 5).
Two processes serve the app: `scripts/run_webapp.py` +
`scripts/run_extraction_worker.py --loop` (background tasks); the cloudflared
Windows service carries the tunnel.
