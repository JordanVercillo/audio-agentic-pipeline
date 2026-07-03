# The Vercillo Analytics Agentic Harness — Design

Claude Code harness for the audio-agentic-pipeline, instantiated from the
playbook at `C:\Users\jverc\claude-repo-playbook` (the same treatment as the
`wasteland101_4x` and `language-models` repos). Three systems:

| Playbook system | This repo |
|---|---|
| **Memory** (living docs) | `notes/PROJECT_CONTEXT.md` (verified state, session log), `notes/engineering_journal.md`, `notes/project_roadmap.md`; `CLAUDE.md` = stable bootloader; `CLAUDE_INSTRUCTIONS.md` = frozen architecture manual |
| **Automation** (skills) | `pipeline-partner` → `warehouse-audit` worker, `env-verify` |
| **Evidence** (evals) | pytest suite (synthetic-data) + `audit_warehouse.py` (data-quality checks) + Phase-5 before/after artifacts |

**The flywheel:** orient (PROJECT_CONTEXT) → work (one roadmap slice) →
measure (pytest + warehouse-audit) → record (status, results, journal).

## The skills

| Skill | Role | Maps from |
|---|---|---|
| `pipeline-partner` | Orchestrates a feature/design session: recall → audit → design/build with the portfolio lens → measure → update memory | wasteland `design-partner` |
| `warehouse-audit` | Deterministic data-quality validator over the medallion warehouse (`audit_warehouse.py`): layer presence, bridge-key integrity, join coverage, feature-column drift, audio orphans | wasteland `kb-audit` |
| `env-verify` | Environment + test triage: deps, ffmpeg, env vars, pytest, pipeline smoke — PASS/FAIL with copy-pasteable fixes | course `setup-debugger` |

## Domain ground rules the harness enforces

1. `spotify_track_id` is the only join key (CLAUDE.md rule 1) — the audit
   fails on nulls/dupes/orphans against it.
2. Parquet-only persistence; data never committed (rebuildable via
   `scripts/run_pipeline.py`).
3. 2026 Spotify API constraints (`.agent_prompts/01`) — no deprecated
   endpoints, ever.
4. Claims of "working" require a runtime proof: pytest + audit, recorded in
   PROJECT_CONTEXT (journal entry #4 is why).

## Deliberately not built yet

- **uv/pyproject migration** — roadmap W-5 (heavy deps; do it as its own
  tested change). Harness scripts are already uv PEP-723 single-files, so
  they don't depend on the project env.
- **CI workflow** — roadmap W-6; trivial once W-1 verification lands.
- **insight-engine skill** — Phase 5 is product code first; a skill wrapper
  only if report generation becomes a recurring workflow.
