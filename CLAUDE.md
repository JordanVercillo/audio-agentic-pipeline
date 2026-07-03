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

Architecture manual: [`CLAUDE_INSTRUCTIONS.md`](CLAUDE_INSTRUCTIONS.md)
(medallion layers, module map, ADRs, code standards — its "Current State"
table is a frozen 2026-05-06 snapshot; trust PROJECT_CONTEXT for live state).

## Ground rules (non-negotiable)

1. **Never break the bridge key.** `spotify_track_id` (string) is the ONLY
   join key across metadata, audio filenames (`{id}.mp3`), features, and the
   star schema. No second ID system, ever.
2. **Parquet only** for feature matrices and warehouse layers — never CSV.
   `pyarrow` engine. (ADR-006.)
3. **Respect the 2026 Spotify API reality** (`.agent_prompts/01_spotify_api_guardrails.md`):
   `/audio-features`, `/audio-analysis`, and `popularity` are GONE. Audio
   characteristics come from LOCAL DSP only. PKCE auth only.
4. **No secrets in the repo.** Env vars (`SPOTIPY_CLIENT_ID/SECRET/REDIRECT_URI`);
   `.env` is gitignored. Pin CVE-patched dependency minimums (yt-dlp ≥2026.2.21).
5. **Tests use synthetic data** (`generate_test_signal()`) — never require
   real API calls or downloaded audio to pass.
6. **Idempotency is a feature.** Downloads and extractions skip work already
   done (file + Parquet cache). Don't remove those guards.
7. **Data is rebuildable, never committed** — `data/` is gitignored; the
   pipeline scripts are the artifact.

## Run commands

```bash
python scripts/run_pipeline.py                            # full 7-step pipeline
python scripts/run_pipeline.py --skip-download --skip-extract  # metadata-only smoke
pytest src/ -v                                            # test suite
uv run .claude/skills/warehouse-audit/audit_warehouse.py  # data-quality audit
```

## The harness

`.claude/skills/` — `pipeline-partner` (feature/design sessions; reads +
updates PROJECT_CONTEXT automatically), `warehouse-audit` (deterministic
data-quality validator — run after any pipeline run or transform change),
`env-verify` (environment + test triage). Design doc: `.claude/README.md`.
Journal surprises in `notes/engineering_journal.md`.
