# PROJECT CONTEXT — read this first

## ⏭️ RESUME HERE (30-second orientation)

- **Project:** Vercillo Analytics — a data-engineering portfolio pipeline:
  Spotify top tracks (3 time ranges) → YouTube audio acquisition → local DSP
  (77-dim features) → medallion warehouse (Parquet, star schema) → FAISS/UMAP
  + temporal drift analytics. Exists BECAUSE the Feb-2026 Spotify API removed
  `/audio-features` — the local-DSP layer is the interesting part.
- **Portfolio target:** Data Engineer – Platform (Spotify Toronto posting is
  the reference role): pipelines at scale, Spark, developer experience, data
  quality, "systems that enable AI agents to interact with data
  infrastructure" — this repo's agent harness IS evidence for that last one.
- **Status:** Phases 1–3 code present with tests (ingestion / DSP / warehouse
  / search / spark). **Repo hardened + harness installed 2026-07-03.**
  ⚠️ Not yet verified to RUN end-to-end on this machine; warehouse is empty
  (data is gitignored by design, and no local run has landed yet). The
  Phase-4 webapp described in the docs is NOT in this repo copy.
- **➡️ NEXT ACTION — prove the pipeline runs: run `/env-verify` (deps,
  ffmpeg, env vars, pytest), then a metadata-only smoke
  (`python scripts/run_pipeline.py --skip-download --skip-extract`), then a
  small real run; `/warehouse-audit` after each.** Only then start Phase 5.1
  (insight engine) — the portfolio centerpiece.
- **How to work:** `/pipeline-partner` for feature/design sessions (reads and
  updates this file automatically). `/warehouse-audit` after any pipeline run
  or transform change. Ground rules in `CLAUDE.md`.

---

**Purpose.** Master memory file. New session: READ THIS FIRST — caught up, no
re-derivation. Architecture/conventions ground truth is `CLAUDE_INSTRUCTIONS.md`
(module map, ADRs); this file tracks the *work*: verified status, results,
conventions, session log.

**How to update (protocol).** At session END: (a) rewrite status + ➡️ NEXT
ACTION, (b) update the phase-results section, (c) add new key files, (d) append
one dated Session-log line ending "**Left off:** …". Map, not transcript —
narrative goes to `notes/engineering_journal.md`, plans to
`notes/project_roadmap.md`. Fix stale facts on sight.

---

## 1. Key files map

| Path | What it is |
|---|---|
| `CLAUDE.md` | Bootloader: ground rules (bridge key, Parquet-only, API guardrails, synthetic tests). Stable. |
| `CLAUDE_INSTRUCTIONS.md` | The architecture manual: medallion design, module map, 77-dim feature spec, ADR-001…006, code standards, phase roadmap detail. Current-State table frozen at 2026-05-06. |
| `PR_REFERENCE.md` | Historical: the Copilot PR write-up for Phases 1–4. Describes a webapp + git history this repo copy does NOT contain (see journal #4). |
| `notes/project_roadmap.md` | Severity-ranked weaknesses + the phase gameplan with exit criteria. |
| `notes/engineering_journal.md` | Numbered insight journal — surprises, not progress. |
| `src/ingestion/` | Spotify PKCE auth, top-items fetchers, YouTube→MP3 downloader (rate-limited, idempotent), Parquet serializer. Tests: `test_ingestion.py`, `test_audio_downloader.py`. |
| `src/dsp/` | librosa loader, 77-dim feature extractor, batch collection extractor, optional PANNs embeddings. Tests: `test_dsp.py`, `test_collection_extractor.py`. |
| `src/warehouse/` | Medallion: `staging.py` (Bronze) → `cleansed.py` (Silver) → `modeled.py` (Gold star schema; fact denormalized, agent-optimized per ADR-002). |
| `src/search/` | FAISS store, UMAP visualizer, DAG pipeline. Test: `test_search.py`. |
| `src/analysis/` | Temporal drift (cosine, ADR-003) + matplotlib visuals. |
| `spark/` | PySpark jobs: temporal centroid aggregation, feature transform. |
| `scripts/run_pipeline.py` | The 7-step orchestrator (`--clean`, `--skip-download`, `--skip-extract`). |
| `notebooks/` | `pipeline_walkthrough.ipynb`, `temporal_analysis.ipynb` + build script. |
| `.agent_prompts/` | Role prompts: 01 Spotify API guardrails (2026 deprecations), 02 DSP architect, 03 data orchestrator. Imported from working drafts 2026-07-03. |
| `.claude/skills/` | The harness: pipeline-partner, warehouse-audit (+ `audit_warehouse.py`), env-verify. Design doc: `.claude/README.md`. |
| `spotify/` | LEGACY v0 (pre-pipeline standalone scripts + notebook). Fold or archive — roadmap item. |
| `00_tools/notebooks/media_converter.py` | Standalone media→mp3/wav/mp4 utility (beginner-doc style). Unintegrated; overlaps `audio_downloader`. |
| `data/` (gitignored) | `raw_audio/{track_id}.mp3` + `warehouse/{staging,cleansed,modeled}/` Parquet. Rebuild: `run_pipeline.py`. |

## 2. Phase results (verified vs. claimed)

- **Phases 1–3 (code ✅, runtime unverified).** Downloader with
  rate-limit guardrails + exponential backoff + two-layer idempotency;
  77-dim DSP extraction; 7-step orchestrated medallion build. 5 test files
  colocated with modules. requirements.txt CVE-pins yt-dlp/fastapi.
  **No verified local end-to-end run recorded yet** — that's the gate.
- **Phase 4 (webapp) — ABSENT from this repo.** CLAUDE_INSTRUCTIONS +
  PR_REFERENCE describe a FastAPI webapp (OAuth, dark UI, Docker); it was
  never uploaded here. Decision needed: recover, rebuild, or descope
  (roadmap W-3).
- **Phase 5 (insights) — not started.** 5.1 narrative insight engine,
  5.2 genre clustering, 5.3 temporal trend visuals, 5.4 static portfolio
  export. This is the portfolio payoff; details in CLAUDE_INSTRUCTIONS §Phase 5.
- **Repo hardening + harness (2026-07-03 ✅).** Nested `audio-agentic-pipeline/`
  folder flattened to root; `.gitignore` added; committed `__pycache__`/
  anaconda db untracked; `.agent_prompts/` imported; CLAUDE.md bootloader +
  notes/ memory docs + 3 skills installed.

## 3. Working conventions

- **Ground rules** in `CLAUDE.md`; architecture + code standards in
  `CLAUDE_INSTRUCTIONS.md` (Google docstrings, typed signatures, logging not
  print, dataclass configs, snake_case columns).
- **Measure before claiming:** any pipeline/transform change → rerun
  `pytest src/ -v` + `/warehouse-audit`; record row counts and pass/fail here.
  A feature isn't "working" until the audit says the warehouse it produced is
  coherent.
- **Portfolio lens:** every feature should earn a line in the README/demo
  story for a platform-DE audience (scale, quality, DX, agents-on-data).
- **Python env:** currently conda-based (py3.13) + `requirements.txt`.
  Harness scripts are uv single-file (PEP 723) so they run independent of the
  project env. Full uv/pyproject migration = roadmap W-2.
- **Git:** commit-sized reviewable chunks; Jordan pushes. History before
  2026-07-03 is two web-upload commits — treat PR_REFERENCE as narrative, not
  git truth.

## 4. Session log

- **(backfilled) 2026-05:** Copilot-assisted build of Phases 1–4 on a
  separate copy (see PR_REFERENCE). Docs written (CLAUDE_INSTRUCTIONS).
- **(backfilled) 2026-07-03 (upload):** Repo created on GitHub via web
  upload — nested folder, no webapp, bytecode included, README stub.
- **2026-07-03 (this session):** Reviewed repo vs. docs (journal #4).
  Hardened structure (flatten, .gitignore, untrack bytecode/IDE db).
  Installed the playbook harness (bootloader, notes/, 3 skills, warehouse
  audit script) modeled on wasteland101/language-models. **Left off: nothing
  run yet — next is `/env-verify` → metadata-only smoke → small real run →
  `/warehouse-audit`, then Phase 5.1.**
