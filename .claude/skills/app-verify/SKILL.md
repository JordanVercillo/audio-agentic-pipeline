---
name: app-verify
description: Internal skill — deterministic live-system audit of the RUNNING app (webapp, public URL, tunnel service, cache counts, marts, spectrograms, evals). Called by /resume at session start; also usable directly when Jordan asks "is the app up / what state is the system in". Complements warehouse-audit (data) and env-verify (environment).
---

Run the audit and read the JSON report:

```bash
uv run .claude/skills/app-verify/verify_app.py           # full check
uv run .claude/skills/app-verify/verify_app.py --skip-public   # offline/dev
```

Interpretation:
- `WEBAPP_DOWN` — start it: `uv run python scripts/run_webapp.py` (background)
  and the worker: `uv run python scripts/run_extraction_worker.py --loop`.
- `PUBLIC_DOWN` with webapp UP — tunnel path: check `TUNNEL_DOWN`
  (`Start-Service cloudflared`, elevated; see docs/SELF_HOSTING.md §2 gotcha).
- `CACHE_EMPTY` — `uv run python scripts/seed_cache.py --spectrograms`.
- `MARTS_MISSING` — `uv run python scripts/build_feature_marts.py`.
- `WORKER_DOWN` — the extraction worker hasn't beaten within 3 poll intervals
  (min 300s): new visitors' queued tracks are NOT being extracted. Start it:
  `uv run python scripts/run_extraction_worker.py --loop` (background). A
  worker running pre-heartbeat code also reads DOWN — restart it onto current
  code. Confirm which with a process check
  (`Get-CimInstance Win32_Process -Filter "Name like 'python%'"`).
- `QUEUE_STUCK` — a queued/running job untouched >15 min. With WORKER_DOWN:
  start the worker. Alone: the worker is alive but not consuming — inspect its
  console/logs and `extraction_jobs`.
- `jobs_by_status.failed` > 0 — inspect `extraction_jobs.last_error` (a failed
  job re-queues on the next dashboard visit that includes the track).

The report is a *claim check*, not a claim (journal #4/#14): trust flags over
any doc that says "running".
