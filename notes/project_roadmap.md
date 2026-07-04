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
| W-1 | ✅ ~~No verified end-to-end run on this machine~~ | ~~🔴~~ | Repo re-uploaded; env never re-validated | **RESOLVED 2026-07-03**: smoke (150 entries) + real run (9 tracks, audio+DSP) + audit ALL-GREEN. En route: secret scrubbed (ROTATE in dashboard!), orchestrator rebuilt, ffmpeg/libmp3lame fixed, feature serialization gap closed (82 warehouse cols; vector stays 77) |
| W-2 | ✅ ~~Repo structure/hygiene~~ (nested root, committed bytecode, no .gitignore, stub README) | ~~🔴~~ | GitHub web upload | **RESOLVED 2026-07-03** (flatten + gitignore + harness) |
| W-3 | **Phase-4 webapp missing** while docs claim it ✅ | 🟠 Med | Upload lost it (or it never left the Copilot copy) | **DECIDED 2026-07-03 (SPEC D-7):** rebuild as P8 production pilot — per-visitor PKCE auth (no secret), feature-store joins, RAG insights |
| W-4 | ✅ ~~Phase 5 not started~~ | ~~🟠~~ | Gated by W-1 | **RESOLVED 2026-07-03** (SPEC P1–P4: taste map, insight engine, σ-honest trend charts, single-file taste_report.html — `build_report.py` meets the "one command from a fresh warehouse" exit criterion) |
| W-5 | **Env not reproducible** — conda + requirements.txt, no lockfile; heavy deps (pyspark, faiss, librosa) | 🟡 Low (until W-1 forces it) | Pre-uv era | Migrate to uv + `pyproject.toml` + lock; keep requirements.txt export for compat |
| W-6 | **No CI** — tests exist but nothing runs them automatically | 🟡 Low | Never set up | GitHub Actions: ruff + pytest (synthetic-data tests make this free) — strong platform-DE signal |
| W-7 | **Legacy code unintegrated** — `spotify/` v0 scripts, `00_tools/media_converter.py` | 🟡 Low | Accretion | Archive to `legacy/` or fold useful bits into `src/` |
| W-8 | **README is generic** — no results, no architecture diagram, no demo path for a recruiter/engineer reading 90 seconds | 🟡 Low (until Phase 5 gives results) | Pre-results | Portfolio-grade rewrite after Phase 5.1 lands |

## The gameplan

> **2026-07-03: the gameplan detail below is superseded by [`SPEC.md`](../SPEC.md)**
> (approved design: phases P0–P7 with acceptance criteria + decision log).
> This file remains the weakness ledger; W-numbers map to spec phases:
> W-3 → **DECIDED (owner override D-7): webapp reinstated as SPEC P8
> production pilot** (public PKCE auth per visitor, RAG insights) ·
> W-4 → P0–P4 · W-5/W-6 → P6 · W-7 → P6 (legacy archival) ·
> W-8 → P6 (README rewrite).

### ✅ Phase 0 — Repo hardening + harness (DONE 2026-07-03)
Flatten, .gitignore, untrack junk, import `.agent_prompts/`, install
bootloader + notes/ + skills. *(W-2)*

### ✅ Phase V — Verify the pipeline (DONE 2026-07-03)
1. ✅ `/env-verify`: conda base py3.13.5 is the env (bare `python` is a
   dep-less 3.11 — invoke conda explicitly); 55/55 tests; yt-dlp 2026.03.17;
   ffmpeg needed the Gyan build (conda's lacks libmp3lame).
2. ✅ Metadata-only smoke: 150 track entries / 117 unique / 105 artist
   entries → full Bronze→Silver→Gold build in 62.5s.
3. ✅ Real run (`--limit 4`): 9/9 downloads, 9/9 DSP extractions →
   `/warehouse-audit` ALL-GREEN (zero errors, all flags false; only soft
   "108 not yet downloaded").
*Exit criteria met;* results in PROJECT_CONTEXT §2. Fixed en route: committed
secret scrubbed (rotation still owed), 7-step orchestrator rebuilt to match
docs (+ `--limit N`), feature-serialization gap closed. *(W-1)*

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
