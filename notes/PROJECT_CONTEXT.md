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
- **Status:** ✅ **Phase V VERIFIED 2026-07-03 — the pipeline runs end-to-end
  on this machine and the warehouse passes its audit ALL-GREEN** (see §2:
  smoke + 9-track real run w/ audio download + DSP). Fixed during
  verification: committed Spotify secret scrubbed (⚠️ **rotation in the
  dashboard still owed** — old secret is burned in git history), 7-step
  orchestrator rebuilt to match docs, ffmpeg/libmp3lame installed, DSP
  feature-serialization gap closed (warehouse: 82 numeric feature cols;
  FAISS vector unchanged at 77). Phase-4 webapp still NOT in this repo copy.
- **➡️ NEXT ACTION — SPEC P6: platform hardening (the standardization/DX
  pass).** uv migration (`pyproject.toml` + lockfile; keep requirements.txt
  export) · ruff · GitHub Actions CI (lint + pytest, synthetic-only, no
  secrets) · complete `column_descriptions` to the full schema and switch
  the audit from ±7 tolerance to **exact column-list verification** (D-4) ·
  archive legacy (`spotify/`, `00_tools/media_converter.py` → `legacy/`) ·
  README rewrite (90-second reviewer path, SPEC §8). Accept: CI green on a
  clean clone. **P0–P5 COMPLETE (2026-07-03)** — Phase 5 done AND the P5
  agent layer shipped (MCP server, 145 tests green). Remaining after P6:
  P7 (Spark scale slice), P8 (production-pilot webapp). Design: `SPEC.md`.
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
| `SPEC.md` | **The approved design (2026-07-03):** vision, JD/resume-gap mapping, phases P0–P7 w/ acceptance criteria, non-goals, decision log. Supersedes CLAUDE_INSTRUCTIONS' roadmap + roadmap.md gameplan detail. |
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
| `scripts/run_pipeline.py` | The 7-step orchestrator (`--clean`, `--skip-download`, `--skip-extract`, `--limit N`). REBUILT 2026-07-03 — the uploaded copy was a notebook-runner; this now matches the CLAUDE_INSTRUCTIONS step table. |
| `.env` (local only, gitignored) | `SPOTIPY_CLIENT_ID` + `SPOTIPY_REDIRECT_URI` — that's ALL. PKCE-only project: no client secret exists anywhere (code/env/deploy) as of 2026-07-03. auth.py has no in-code fallbacks. |
| `notebooks/` | `pipeline_walkthrough.ipynb`, `temporal_analysis.ipynb` + build script. |
| `.agent_prompts/` | Role prompts: 01 Spotify API guardrails (2026 deprecations), 02 DSP architect, 03 data orchestrator. Imported from working drafts 2026-07-03. |
| `.claude/skills/` | The harness: pipeline-partner, warehouse-audit (+ `audit_warehouse.py`), env-verify. Design doc: `.claude/README.md`. |
| `src/analysis/clustering.py` | SPEC P1: 77-dim-space KMeans + coarse-genre rules + acoustic cluster naming. `VECTOR_77_COLUMNS` = the contract column list. Test: `test_clustering.py`. |
| `scripts/build_taste_map.py` | One command → `artifacts/taste_map.png` + `modeled/cluster_assignments.parquet`. Deterministic (seed 42). |
| `src/analysis/insights.py` | SPEC P2: pure section builders → versioned `insights.json` (schema v1) + `INSIGHTS.md`. Pipeline step 8. Optional LLM polish (D-5: additive, never load-bearing). Test: `test_insights.py`. |
| `scripts/build_insights.py` | One command → `artifacts/insights.json` + `artifacts/INSIGHTS.md` (`--llm-polish` optional). |
| `scripts/build_trend_charts.py` | SPEC P3: one command → 4 σ-normalized trend PNGs in `artifacts/` (radar, heatmap, distributions, artist flow). Test: `src/analysis/test_visualizations.py`. |
| `src/export/` | SPEC P4: `portfolio.py` (pure Jinja2 render, autoescape — P8-safe) + `templates/portfolio.html`. Test: `test_export.py` (self-containment + XSS). |
| `scripts/build_report.py` | THE one command: fresh gold layer → regenerate all artifacts → `taste_report.html` (0.99 MB, offline). `--no-rebuild`, `--llm-polish`. |
| `src/agent/` | SPEC P5: `warehouse_agent.py` (pure DuckDB retrieval core — 2-layer SQL security D-10; reused by P8 RAG) + `mcp_server.py` (FastMCP stdio: get_schema / query_warehouse / get_insights). Test: `test_agent.py` (30). Run: `python -m src.agent.mcp_server`. |
| `docs/AGENT_ACCESS.md` | P5 artifact: MCP registration config (Claude Desktop/Code) + security model + live demo transcript. |
| `artifacts/` | COMMITTED portfolio outputs (PNGs, reports) — unlike `data/`, these are deliverables. |
| `spotify/` | LEGACY v0 (auth tombstoned 2026-07-03 — PKCE-only project). Archive to `legacy/` in P6. |
| `00_tools/notebooks/media_converter.py` | Standalone media→mp3/wav/mp4 utility (beginner-doc style). Unintegrated; overlaps `audio_downloader`. |
| `data/` (gitignored) | `raw_audio/{track_id}.mp3` + `warehouse/{staging,cleansed,modeled}/` Parquet. Rebuild: `run_pipeline.py`. |

## 2. Phase results (verified vs. claimed)

- **Phases 1–3 (✅ VERIFIED 2026-07-03).** End-to-end proven on this machine:
  - **Env:** conda base py3.13.5 (see §3 for invocation); 55/55 pytest.
  - **Smoke** (`--skip-download --skip-extract`, 62.5s): 150 track entries
    (50×3 ranges, 117 unique), 105 artist entries → staging → cleansed →
    star schema (fact 150 rows, dim_tracks 117, dim_artists 59). Audit:
    zero errors, expected FEATURE_DRIFT only (no features yet).
  - **Real run** (`--limit 4`): 9 unique tracks — 9/9 YouTube downloads
    (192kbps MP3, `{id}.mp3`), 9/9 DSP extractions. First attempt failed
    9/9: conda ffmpeg lacks libmp3lame (journal #7) → Gyan FFmpeg 8.1.2 via
    winget. Rerun: all green in 290.5s; idempotency + Silver dedup observed
    working (12 dup rows removed across snapshots).
  - **Final audit ALL-GREEN:** errors 0; every flag false; fact 150 rows ×
    82 numeric feature cols; 9 MP3s ↔ metadata fully reconciled; only soft
    warning "108 tracks not yet downloaded".
  - **Feature contract clarified (journal #8):** `to_summary_vector()` = the
    frozen 77-dim FAISS contract (untouched). Warehouse tables now carry 82
    numeric feature cols (chroma_std ×12 + spectral_contrast_std ×7 were
    computed-but-never-serialized; spectral_bandwidth ×2 + flatness ×1 were
    spec'd-but-never-computed — all added). CLAUDE_INSTRUCTIONS' 77-table
    is imprecise (different membership than the vector's 77) — doc fix
    pending, audit tolerance ±7 covers it.
  - **Security (⚠️ action owed):** hardcoded client ID+SECRET removed from
    `auth.py` and legacy `spotify/spotify_config.py`; `.env` created;
    `.gitignore` now covers `data/` (PKCE token cache). **The old secret
    shipped in the public upload commits — Jordan must rotate it in the
    Spotify Developer Dashboard.**
- **SPEC P0 — full-corpus run (✅ COMPLETE 2026-07-03, 56.6 min).**
  Detached run `run_20260703_145234` + completion check: fetch 150 entries
  (117 unique) + 105 artists; downloads **108/108 success, 0 failed,
  0 no_match** (9 skipped-cached); DSP **108/108 extracted, 0 failed**.
  Warehouse: 117 MP3s all reconciled; cleansed_features 117×87 (82 numeric);
  fact 151×93; dim_tracks 118; dim_artists 60. **Audit ALL-GREEN** — only
  soft note: 1 metadata-only track (fell out of top-50 between the morning
  smoke and evening fetch — snapshot-union semantics working as designed;
  will self-heal if it re-enters the charts). PKCE-only auth proved live
  end-to-end (zero secret anywhere).
- **Old Copilot webapp — DECIDED (D-7): reinstated as SPEC P8 production
  pilot** (public site, per-visitor PKCE auth, RAG over the P5 core). The
  original FastAPI upload was never in this repo; P8 rebuilds lean. Not
  started; sequenced after P6.
- **SPEC P1 — taste map (✅ COMPLETE 2026-07-03, audit ALL-GREEN).**
  - **Warehouse:** artists path finished end-to-end — `fetch_artists_by_ids`
    (batch GET /artists) backfills primary artists missing from top-artists
    (28 backfilled, 1 API call); `build_cleansed_artists` (94×6, one row per
    artist); `dim_artists` enriched with genres (60×6). Track-level genre
    coverage **81/118** — the honest ceiling; Spotify 2026 genre arrays are
    often empty (journal #9).
  - **Clustering (`src/analysis/clustering.py`):** clusters in EXACTLY the
    frozen 77-dim vector space (`VECTOR_77_COLUMNS` mirrors
    `to_summary_vector`); standardized + L2-normalized (KMeans euclidean ≈
    cosine, ADR-003 doctrine); k by silhouette (chose k=3, 0.094 — music is
    a continuum, honest); deterministic (seed 42, verified by unit test).
    Clusters named ACOUSTICALLY via centroid z-scores ("Smooth · Dark" /
    "Noisy · Bright" / "Gentle · Loud") because genre metadata degenerates
    under a dominant artist (journal #9).
  - **Artifacts:** `artifacts/taste_map.png` (committable README hero;
    genre-colored, sized by temporal persistence, cluster-annotated) +
    `modeled/cluster_assignments.parquet` (117×8, bridge-keyed, audit-clean).
  - **Tests:** 23 in `src/analysis/test_clustering.py` + 7 in new
    `src/warehouse/test_warehouse.py` → suite total 85, all green.
  - One command rebuilds: `python scripts/build_taste_map.py`.
- **SPEC P2 — insight engine (✅ COMPLETE 2026-07-03).**
  - **`src/analysis/insights.py`:** pure section builders (corpus, drift,
    clusters, persistence, superlatives, genres) → versioned
    `artifacts/insights.json` (schema v1 — the contract P5's MCP
    `get_insights()` and P8's RAG read) + templated `artifacts/INSIGHTS.md`.
    Runs as **pipeline step 8** (skips politely on metadata-only smokes);
    standalone: `python scripts/build_insights.py [--llm-polish]`.
  - **LLM polish (SPEC D-5 honored):** optional executive-summary prose via
    Claude API (`claude-opus-4-8` default, `INSIGHTS_LLM_MODEL` override);
    adds a clearly-marked section, never touches deterministic tables,
    silently degrades on any failure (no SDK/credentials/API error).
  - **Drift metric FIXED en route (ADR-003 amended, D-9, journal #10):**
    cosine flatlined at 0.0000 on raw centroids (scale domination) and
    pegged at 1.4998 on z-centroids (centering geometry) — replaced with
    **RMS σ-shift** between standardized centroids. Sanity anchors:
    constant corpus 0.0 / strong synthetic ~2σ / real corpus **0.1405σ
    (Minimal Drift, stability 0.859)** — credible for this corpus (9
    all-three-ranges favorites, Muse ×31).
  - **Tests:** 13 in `test_insights.py` (schema-stability, crafted-winner
    superlatives, persistence counts, drift anchors, markdown determinism)
    → suite total 98, all green.
- **SPEC P3 — temporal trend visuals (✅ COMPLETE 2026-07-03).**
  - `python scripts/build_trend_charts.py` → 4 deterministic PNGs in
    `artifacts/`: `drift_radar.png`, `temporal_heatmap.png`,
    `feature_distributions.png`, `artist_flow.png` — each one plotter
    function fed from the gold layer alone.
  - **Honesty fix (journal #10 postscript):** radar/heatmap min-max
    normalization over 3 window-centroids pinned every axis to [0,1] by
    construction (a 0.75% brightness shift rendered as full-scale
    divergence, contradicting the 0.14σ verdict). Both plotters now take
    `corpus_stats` and normalize in σ units — radar rings = 1σ, heatmap
    diverging ±1σ — so visual divergence = effect size = drift-score
    units. Legacy min-max kept as fallback for the notebook path.
  - **plot_umap_by_time_range deliberately EXCLUDED** from artifacts: it
    recomputes UMAP on raw unscaled features (scale-domination artifact)
    and multi-range tracks would plot identical overlapping points;
    `taste_map.png` (P1) is the canonical projection.
  - Tests: 10 in `test_visualizations.py` (render + σ-mode + zero-std +
    degenerate inputs) → suite total 108, all green.
- **SPEC P4 — portfolio export (✅ COMPLETE 2026-07-03) → PHASE 5 DONE.**
  - `python scripts/build_report.py` = ONE command from a fresh gold layer:
    regenerates taste map + insights + trend charts (all deterministic),
    then renders **`artifacts/taste_report.html` — 0.99 MB, single file,
    every image a base64 data: URI, opens offline** (test-enforced: no
    external/file refs, no scripts).
  - `src/export/portfolio.py` (pure render, Jinja2 **autoescape ON** — track
    names are untrusted; P8 renders other users' libraries through this
    template, XSS-escape test included) + `templates/portfolio.html`
    (dark GitHub theme matching the charts).
  - Report sections: hero (drift σ / stability / persistent favorites),
    taste map + cluster table, σ-unit charts, top-10 per window,
    staying power + superlatives, genre chips, methodology footer
    (API-deprecation origin story, PKCE-no-secret, medallion, σ-shift).
  - Verified rendered in a browser (a11y snapshot: all sections + images
    load, zero console errors). Tests: 7 in `src/export/test_export.py` →
    suite total **115**, all green.
  - **Roadmap Phase-5 exit criterion met**; W-4 resolved.
- **SPEC P5 — Agent Access Layer / MCP (✅ COMPLETE 2026-07-03).**
  - **`src/agent/warehouse_agent.py`** — pure retrieval core (DuckDB +
    pandas, no MCP import): `get_schema()` (tables/cols/types + agent
    descriptions from `column_descriptions` + join-key notes),
    `query_warehouse(sql)` (read-only, returns `{ok,columns,rows,row_count,
    truncated}`, never raises), `get_insights()` (serves insights.json v1).
    Reused verbatim by P8's RAG.
  - **Security (D-10, journal #11) — two layers:** statement guard
    (`is_safe_sql`: single SELECT/WITH, denylist verbs+file-funcs) for a
    clear read-only contract; the REAL boundary is the DuckDB sandbox —
    gold Parquet → native in-memory tables → `enable_external_access=false`
    + `lock_configuration=true`. Bypassing the guard still can't read a file
    (PermissionException) or re-enable access (InvalidInputException); both
    proven by test.
  - **`src/agent/mcp_server.py`** — thin FastMCP stdio wrapper, lazy agent
    init, logs→stderr (stdout is JSON-RPC). Run: `python -m src.agent.mcp_server`.
  - **Deps added** (conda env + requirements): `mcp>=1.2.0`, `duckdb>=1.1.0`,
    `jinja2>=3.1.0`. pydantic auto-bumped 2.10→2.13, no breakage.
  - **Verified:** real MCP stdio handshake (initialize → list_tools =
    [get_schema, query_warehouse, get_insights] → query returns Muse 31 /
    Linkin Park 6 / Green Day 5 → DROP rejected); 5 live taste questions
    answered against the real warehouse; `docs/AGENT_ACCESS.md` has the
    registration config + transcript. Tests: 30 in `src/agent/test_agent.py`
    → suite total **145**, all green.
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
- **Python env (verified 2026-07-03):** conda BASE env is the project env —
  invoke as `C:\Users\jverc\anaconda3\python.exe` (py3.13.5, all deps incl.
  python-dotenv). ⚠️ Bare `python` on PATH is an unrelated dep-less 3.11.
  For runs with downloads, put Gyan FFmpeg first on PATH
  (`%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-8.1.2-full_build\bin`)
  — conda's ffmpeg lacks libmp3lame. Harness scripts are uv single-file
  (PEP 723) so they run independent of the project env. Full uv/pyproject
  migration = roadmap W-5.
- **Git:** commit-sized reviewable chunks; Jordan pushes. History before
  2026-07-03 is two web-upload commits — treat PR_REFERENCE as narrative, not
  git truth.

## 4. Session log

- **(backfilled) 2026-05:** Copilot-assisted build of Phases 1–4 on a
  separate copy (see PR_REFERENCE). Docs written (CLAUDE_INSTRUCTIONS).
- **(backfilled) 2026-07-03 (upload):** Repo created on GitHub via web
  upload — nested folder, no webapp, bytecode included, README stub.
- **2026-07-03 (session 1):** Reviewed repo vs. docs (journal #4).
  Hardened structure (flatten, .gitignore, untrack bytecode/IDE db).
  Installed the playbook harness (bootloader, notes/, 3 skills, warehouse
  audit script) modeled on wasteland101/language-models. **Left off: nothing
  run yet — next is `/env-verify` → metadata-only smoke → small real run →
  `/warehouse-audit`, then Phase 5.1.**
- **2026-07-03 (session 2 — Phase V verification):** env-verify found the
  real env (conda base 3.13.5; 55/55 tests) plus a committed Spotify secret
  (scrubbed from auth.py + legacy config; journal #5) and a fictional run
  command — rebuilt `run_pipeline.py` as the documented 7-step orchestrator
  (journal #6). Smoke run green (150 entries, 62.5s). Real run: first
  attempt 0/9 downloads (conda ffmpeg lacks libmp3lame → winget Gyan build;
  journal #7), rerun 9/9 downloads + 9/9 DSP. Audit flagged the feature
  contract: to_summary_dict dropped 19 computed cols, 3 spec'd cols never
  computed — fixed extractor (warehouse 82 cols; vector stays 77; journal
  #8), patched audit META_COLS + column_descriptions exemption, re-extracted.
  **Final audit ALL-GREEN — W-1 RESOLVED, Phase V complete.** env-verify
  skill upgraded (capability checks). **Left off: warehouse verified but
  only 9/117 tracks have audio+features — next session: full run
  (`run_pipeline.py`, ~1.5–3 h background) + audit, then Phase 5.2 genre
  clustering. ⚠️ Jordan: rotate the Spotify client secret, then commit +
  push this session's changes (working tree only — nothing committed yet).**
- **2026-07-03 (session 3 — design/spec):** Jordan handed over lead design
  with the old working-folder materials (Copilot-era CLAUDE_INSTRUCTIONS +
  PR_REFERENCE, agent prompts, rendered temporal_analysis outputs, the
  Spotify Platform JD, resume). Wrote **`SPEC.md` v1.0**: vision anchored on
  the 2026 API-deprecation origin story; JD/resume-gap evidence mapping
  (day job proves BigQuery/Dataform — this repo must prove production
  Python, working Spark, CI, and BUILDING agent-data systems); phases P0–P7
  with acceptance criteria; AI in three deterministic-first roles. Key
  decisions: webapp DESCOPED (D-1), MCP Agent Access Layer added as P5
  (D-2), Spark-first scale slice w/ BigQuery stretch (D-3), feature
  contract becomes an exact column list in the audit (D-4). Doc map
  aligned: CLAUDE.md + roadmap now point at SPEC. **Left off: no code
  changes this session — next is SPEC P0 (full-corpus run + audit), then
  P1 taste map. Secret rotation still owed.**
- **2026-07-03 (session 4 — PKCE purge + P0 launch + pilot decision):**
  Jordan approved the spec, exercised owner override on the webapp (→ SPEC
  D-7: P8 production pilot — public site, per-visitor PKCE auth, RAG
  insights over a bridge-key feature store), and is rotating the old
  secret. Executed the **PKCE-only purge (D-8)**: deleted
  `get_public_spotify`/client-credentials flow from auth.py, fetchers now
  default to the PKCE client, exports/tests/notebook updated, legacy
  spotify_config tombstoned, `.env`/CLAUDE.md/env-verify/PR_REFERENCE
  scrubbed — zero `SPOTIPY_CLIENT_SECRET` references remain repo-wide;
  55/55 tests green. **Launched P0** (detached, pid 18852, snapshot
  `run_20260703_145234`, limit=50): PKCE auth from cache, downloads
  streaming. SPEC amended (P8, D-7/D-8, risks: dev-mode 25-user allowlist
  gate, pilot privacy). **Left off: P0 downloading in background — on
  completion run `/warehouse-audit`, record P0 numbers, then P1. Rotation
  in Jordan's hands.**
- **2026-07-03 (session 4, completion check):** P0 finished in 56.6 min —
  108/108 downloads, 108/108 extractions, zero failures; audit ALL-GREEN at
  full scale (117 MP3s, fact 151×93, 82 numeric feature cols; 1 soft
  metadata-only track from inter-snapshot chart movement). P0 acceptance
  criteria met; evidence recorded in §2. **Left off: warehouse is
  portfolio-ready — next is SPEC P1 (taste map: clustering.py + UMAP genre
  visual). Secret rotation still in Jordan's hands.**
- **2026-07-03 (session 5 — SPEC P1 built + accepted):** Artists path
  (batch genre backfill → cleansed_artists → enriched dim_artists; coverage
  81/118), `clustering.py` (77-dim contract space, cosine-normalized KMeans,
  silhouette k=3, deterministic), acoustic cluster naming after genre
  labels degenerated under a Muse-dominated corpus (journal #9),
  `build_taste_map.py` → `artifacts/taste_map.png` + bridge-keyed
  `cluster_assignments.parquet`. All 4 SPEC P1 acceptance criteria met;
  audit ALL-GREEN; 85 tests green. scikit-learn pinned in requirements.
  **Left off: P1 done — next is SPEC P2 (insight engine:
  `src/analysis/insights.py` → insights.json → INSIGHTS.md, pipeline step
  8). Secret rotation + commits still in Jordan's hands.**
- **2026-07-03 (session 6 — SPEC P2 built + accepted):** Insight engine
  shipped: pure section builders → schema-versioned insights.json +
  INSIGHTS.md; pipeline step 8 (8-step orchestrator now; smoke runs skip
  politely); `--llm-polish` per D-5 (claude-opus-4-8, additive-only,
  graceful degradation). **The drift instrument was broken and got fixed
  properly (journal #10):** cosine-on-raw read 0.0000 (scale domination),
  cosine-on-z read 1.4998 (centering forces ~120° angles) — final metric
  RMS σ-shift with sanity anchors at both ends; ADR-003 amended (SPEC D-9).
  Real corpus: **0.1405σ Minimal Drift, stability 0.859**. 98 tests green.
  **Left off: P2 done — next is SPEC P3 (temporal trend visuals wired to
  the real warehouse → artifacts/ PNGs). Secret rotation + commits still
  in Jordan's hands; consider committing P0–P2 as reviewable chunks.**
- **2026-07-03 (session 7 — SPEC P3 built + accepted):** 4 trend charts
  shipped via `build_trend_charts.py` (radar, heatmap, distributions,
  artist flow — one plotter each from the gold layer). Caught + fixed the
  visual twin of journal #10: min-max over 3 centroids pins axes to [0,1],
  amplifying 0.75% shifts to full scale — both charts now σ-normalized via
  `corpus_stats` so they AGREE with the 0.14σ drift verdict.
  `plot_umap_by_time_range` deliberately excluded (raw-cosine UMAP +
  duplicate-point occlusion); taste_map.png stays canonical. 108 tests
  green. **Left off: P3 done — next is SPEC P4 (single-file
  `taste_report.html`: Jinja2 + inline CSS + base64 PNGs + insights.json
  narrative; <10 MB, offline). Rotation + commits in Jordan's hands.**
- **2026-07-03 (session 8 — SPEC P4 built + accepted → PHASE 5 COMPLETE):**
  `src/export/` (pure Jinja2 render, autoescape + XSS test for P8 reuse) +
  `scripts/build_report.py` (regenerates ALL inputs deterministically, then
  renders). `taste_report.html`: 0.99 MB, fully self-contained
  (test-enforced), verified rendering in a browser via a11y snapshot.
  Determinism reconfirmed end-to-end on the rebuild (same k=3, same
  0.1405σ). 115 tests green. W-4 resolved — roadmap Phase-5 exit criterion
  met. **Left off: Phase 5 (P1–P4) done — next is SPEC P5 (MCP Agent
  Access Layer: get_schema / query_warehouse read-only / get_insights).
  Rotation + commits in Jordan's hands — the tree now holds P0–P4.**
- **2026-07-03 (session 9 — SPEC P5 built + accepted):** Agent Access Layer
  shipped. Pure `warehouse_agent.py` core + thin `mcp_server.py` (FastMCP
  stdio); 3 tools (schema / read-only query / insights). Security is
  capability-removal not denylist (D-10, journal #11): DuckDB native
  in-memory tables + `enable_external_access=false` + `lock_configuration=
  true` — sandbox proven to block file reads even when the SQL guard is
  bypassed. Installed mcp + duckdb (+ jinja2 pin); pydantic 2.10→2.13, no
  breakage. Verified via a real MCP stdio handshake + 5 live taste
  questions; wrote `docs/AGENT_ACCESS.md`. 30 new tests → **145 green**.
  **Left off: P5 done — next is SPEC P6 (platform hardening: uv/pyproject +
  lockfile, ruff, GitHub Actions CI, exact feature-contract audit per D-4,
  legacy archival, README rewrite). ⚠️ Still owed by Jordan: rotate the old
  Spotify secret + commit/push (tree now holds P0–P5, uncommitted).**
