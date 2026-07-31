# CLAUDE.md — Vercillo Analytics (audio-agentic-pipeline) working agreements

Python data-engineering portfolio project: Spotify top-tracks metadata + local
DSP feature extraction (YouTube-sourced audio) → medallion warehouse → taste
analytics. Owner: Jordan Vercillo. Portfolio target: Data Platform /
Data Engineer roles (pipelines, Spark, data quality, AI-agent-ready data).

## ⏭️ RESUME HERE (read first, every session)

**Before anything else, read [`notes/PROJECT_CONTEXT.md`](notes/PROJECT_CONTEXT.md).**
It is the project's living memory — verified status, next action, key files,
conventions, session log — updated at the end of every session. This file
holds only stable rules; status is deliberately NOT here.

Design spec: [`SPEC.md`](SPEC.md) — approved vision, phase plan (P0–P7) with
acceptance criteria, and decision log (2026-07-03). Architecture manual:
[`CLAUDE_INSTRUCTIONS.md`](CLAUDE_INSTRUCTIONS.md) (medallion layers, module
map, ADRs, code standards — its "Current State" table is a frozen 2026-05-06
snapshot and its roadmap is superseded by SPEC.md; trust PROJECT_CONTEXT for
live state).

## Ground rules (non-negotiable)

1. **Never break the bridge key.** `spotify_track_id` (string) is the ONLY
   join key across metadata, audio filenames (`{id}.mp3`), features, and the
   star schema. No second ID system, ever.
2. **Parquet only** for feature matrices and warehouse layers — never CSV.
   `pyarrow` engine. (ADR-006.)
3. **Respect the 2026 Spotify API reality** (`.agent_prompts/01_spotify_api_guardrails.md`):
   `/audio-features` and `/audio-analysis` are GONE — audio characteristics
   come from LOCAL DSP only. `popularity` is **deprecated-NOT-removed**
   (verified live 2026-07-09, journal #20): captured as optional fetched
   *context* — display/analysis only, **never** an acoustic feature and
   **never** an ML input (Spotify's terms); nothing may hard-depend on it.
   PKCE auth only.
4. **No secrets, period — PKCE-only auth.** No client secret exists anywhere
   in this project (code, env, deployment); the only credentials are
   `SPOTIPY_CLIENT_ID` (public by design) + `SPOTIPY_REDIRECT_URI` via env
   or gitignored `.env`. Pin CVE-patched dependency minimums (yt-dlp ≥2026.2.21).
5. **Tests use synthetic data** (`generate_test_signal()`) — never require
   real API calls or downloaded audio to pass.
6. **Idempotency is a feature.** Downloads and extractions skip work already
   done (file + Parquet cache). Don't remove those guards.
7. **Data is rebuildable, never committed** — `data/` is gitignored; the
   pipeline scripts are the artifact.

## How to explain things here (owner, 2026-07-31)

**Speak analytics-engineering and data-science, not systems-engineering.**
Jordan's frame of reference is the modern data stack and the DS workflow; that
is the vocabulary a Data Platform / DE interview will use too, so explaining in
it doubles as rehearsal.

Reach for: **sources · models · grain · primary key · lineage · upstream /
downstream · DAG · materialization (view vs table vs incremental) · idempotent
rebuild · slowly-changing dimension · freshness SLA · data contract · schema
evolution · tests/assertions · semantic layer · fact vs dimension** — and on the
DS side **feature store · feature engineering · embedding space · dimensionality
reduction · exact vs approximate k-NN · recall@k · train/serve skew · leakage ·
drift · cardinality · z-score / percentile rank · silhouette · centroid**.

Translate rather than assume: when something is really a systems concern (a
thread pool, a mutex, a file handle), say what it costs in *pipeline* terms —
latency per model run, rows per rebuild, whether it changes the grain, whether
it breaks idempotency.

Do NOT jargon-stuff. The test is whether an analytics engineer reading it can
predict what breaks. If a plain sentence is clearer, use the plain sentence.

## Run commands

```bash
python scripts/run_pipeline.py                            # full 8-step pipeline
python scripts/run_pipeline.py --skip-download --skip-extract  # metadata-only smoke
python scripts/build_taste_map.py                         # SPEC P1: taste map artifact
python scripts/build_insights.py [--llm-polish]           # SPEC P2: insights artifacts
python scripts/build_trend_charts.py                      # SPEC P3: trend chart PNGs
python scripts/build_report.py                            # SPEC P4: single-file taste_report.html
python -m src.agent.mcp_server                            # SPEC P5: MCP server over the gold warehouse
pytest src/ -v                                            # test suite
uv run .claude/skills/warehouse-audit/audit_warehouse.py  # data-quality audit
```

MCP registration + demo transcript: [`docs/AGENT_ACCESS.md`](docs/AGENT_ACCESS.md).

## The harness

The session loop is **`/resume` → work → `/wrap-session`**.

| Want | Use |
|---|---|
| Get back up to speed & continue (start here) | `/resume` |
| Save this session to memory + push (end here) | `/wrap-session` |
| Feature / design session (generalist partner) | `/pipeline-partner` |
| Lead a build spanning ≥2 domains (advisory agents) | `/orchestrator` |
| Data-quality audit — after any pipeline run / transform change | `/warehouse-audit` |
| Is the live app up? what state is the system in? | `/app-verify` |
| Environment broken / imports fail / tests won't run | `/env-verify` |

Skills live in `.claude/skills/`; domain-expert agents (advise by default,
in-lane, never commit) in `.claude/agents/` — `data-platform-expert`,
`webapp-expert`, `dsp-expert`, `llm-rag-expert`, `research-expert`,
`agile-coach`, `chat-analyst-expert`, `ui-ux-expert`. Design doc: `.claude/README.md`.
Journal surprises in `notes/engineering_journal.md`.
