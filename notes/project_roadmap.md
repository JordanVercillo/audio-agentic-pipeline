# Project Roadmap — Weaknesses & Gameplan

Portfolio project. The organizing principle (from the playbook): **prove the
measurement instrument first** — here that means *a verified end-to-end run +
a warehouse that passes its own audit* before building the flashy Phase-5
layer on top.

**Portfolio target** (reference role: Spotify Data Engineer – Platform,
Toronto): large-scale batch/real-time pipelines, Spark, developer experience
and standardization, data quality, and *"systems that enable AI agents to
effectively interact with and leverage data infrastructure."* Every roadmap
item below should strengthen that story.

---

## Weakness assessment (severity-ranked)

| # | Weakness | Severity | Root cause | Where it gets fixed |
|---|---|---|---|---|
| W-1 | **No verified end-to-end run on this machine** — code claims ≠ runtime proof; warehouse empty | 🔴 Gating | Repo re-uploaded; env never re-validated | env-verify → smoke run → small real run → warehouse-audit |
| W-2 | ✅ ~~Repo structure/hygiene~~ (nested root, committed bytecode, no .gitignore, stub README) | ~~🔴~~ | GitHub web upload | **RESOLVED 2026-07-03** (flatten + gitignore + harness) |
| W-3 | **Phase-4 webapp missing** while docs claim it ✅ | 🟠 Med | Upload lost it (or it never left the Copilot copy) | Decide: recover / rebuild lean / descope + fix docs |
| W-4 | **Phase 5 not started** — the actual analytical payoff (insights, clustering, temporal trends, portfolio export) | 🟠 Med (High value) | Gated by W-1 | Phase 5.1 → 5.4, spec in CLAUDE_INSTRUCTIONS |
| W-5 | **Env not reproducible** — conda + requirements.txt, no lockfile; heavy deps (pyspark, faiss, librosa) | 🟡 Low (until W-1 forces it) | Pre-uv era | Migrate to uv + `pyproject.toml` + lock; keep requirements.txt export for compat |
| W-6 | **No CI** — tests exist but nothing runs them automatically | 🟡 Low | Never set up | GitHub Actions: ruff + pytest (synthetic-data tests make this free) — strong platform-DE signal |
| W-7 | **Legacy code unintegrated** — `spotify/` v0 scripts, `00_tools/media_converter.py` | 🟡 Low | Accretion | Archive to `legacy/` or fold useful bits into `src/` |
| W-8 | **README is generic** — no results, no architecture diagram, no demo path for a recruiter/engineer reading 90 seconds | 🟡 Low (until Phase 5 gives results) | Pre-results | Portfolio-grade rewrite after Phase 5.1 lands |

## The gameplan

### ✅ Phase 0 — Repo hardening + harness (DONE 2026-07-03)
Flatten, .gitignore, untrack junk, import `.agent_prompts/`, install
bootloader + notes/ + skills. *(W-2)*

### 🎯 Phase V — Verify the pipeline (NEXT — gates everything)
1. `/env-verify`: deps import, ffmpeg present, `SPOTIPY_*` env vars, full
   `pytest src/ -v`.
2. Metadata-only smoke: `python scripts/run_pipeline.py --skip-download
   --skip-extract` → staging/cleansed/modeled build from API data alone.
3. Small real run (a handful of tracks) → `/warehouse-audit` green: bridge-key
   integrity, fact↔dim join coverage, 77 feature columns, no orphans.
*Exit criteria:* audit passes on a real warehouse; results recorded in
PROJECT_CONTEXT §2. *(W-1)*

### 📊 Phase 5 — Insight engine (the portfolio centerpiece)
Build in order of demo value, each with a before/after artifact:
1. **5.2 Genre clustering** (FAISS + UMAP taste map, genre-colored) — the
   money visual.
2. **5.1 Insight narratives** (drift metrics → structured JSON → templated
   markdown; optional LLM polish — keep the deterministic path primary so
   it's testable).
3. **5.3 Temporal trend charts** (radar per time range, drift heatmap).
4. **5.4 Static portfolio export** (single-file HTML — becomes the README
   hero artifact).
*Exit criteria:* one command produces the report from a fresh warehouse. *(W-4, W-8)*

### 🌐 Phase W — Webapp decision *(W-3)*
Recover the Copilot webapp if it exists elsewhere; else rebuild a LEAN
version (top items + the Phase-5 report) or descope and correct the docs.
Don't let docs claim what the repo can't show.

### ☁️ Phase 6 — Platform polish (the job-posting alignment pass)
uv migration *(W-5)* → CI *(W-6)* → legacy cleanup *(W-7)* → then the
cloud story: containerized pipeline, scheduled runs, GCS/BigQuery variant of
the warehouse layer — pick ONE cloud slice and do it well rather than
gesturing at all of them.

## The one-sentence version

> Prove it runs, prove the data is sound, then build the insight layer that
> makes the portfolio demo — and only then polish toward the platform story.
