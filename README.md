# 🎧 Vercillo Analytics — audio-agentic-pipeline

[![CI](https://github.com/JordanVercillo/audio-agentic-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/JordanVercillo/audio-agentic-pipeline/actions/workflows/ci.yml)

**A personal music-analytics data platform that rebuilds the acoustic intelligence Spotify's API deleted** — Spotify listening history → YouTube audio acquisition → local 77-dim DSP → medallion warehouse → taste analytics → an **MCP server that lets AI agents query the warehouse directly.**

> When Spotify removed `/audio-features` for third-party apps in Feb 2026, every project that *consumed* those columns died. This one answers by becoming the **producer**: it acquires real audio, extracts its own feature space, and warehouses it for agents to query.

![Taste map — 117 tracks in 77-dim acoustic space, clustered and genre-colored](artifacts/taste_map.png)

*Every track projected from its own 77-dimension acoustic fingerprint (UMAP + KMeans), colored by genre, sized by how many listening windows it persists in. Clusters are named by what **acoustically** distinguishes them — the vendor's genre tags were too sparse to do it.*

---

## The 90-second tour

**The result:** across three listening windows (last 4 weeks / 6 months / all-time), my taste drift score is **0.14σ — "remarkably stable"** (RMS per-feature shift between standardized acoustic centroids). The full analysis is a single self-contained file: [`artifacts/taste_report.html`](artifacts/taste_report.html) (0.99 MB, opens offline) and [`artifacts/INSIGHTS.md`](artifacts/INSIGHTS.md).

**One command rebuilds every artifact from a fresh warehouse:**

```bash
uv sync                         # reproducible env from uv.lock
python scripts/run_pipeline.py  # 8 steps: fetch → acquire audio → DSP → medallion → insights
python scripts/build_report.py  # taste map + charts + single-file taste_report.html
```

**It's tested and audited — no secrets, no network needed for the test suite:**

```text
$ pytest
148 passed

$ uv run .claude/skills/warehouse-audit/audit_warehouse.py
errors: none · flags: ALL-GREEN · fact 151×93 (82 DSP feature cols, exact-contract verified)
```

**And an AI agent can query it** — the MCP server exposes the gold warehouse as three read-only tools (`get_schema`, `query_warehouse`, `get_insights`):

```text
Q: What's my highest-energy track in each time range?
→ query_warehouse("SELECT time_range, track_name, primary_artist_name, round(rms_mean,3) energy
     FROM fact_listening_features f WHERE rms_mean =
     (SELECT max(rms_mean) FROM fact_listening_features g WHERE g.time_range=f.time_range) ...")
   short_term   Cut Back               — Marmozets     0.305
   long_term    Be With You            — Muse          0.291

Q: [adversarial] SELECT * FROM read_csv('/etc/passwd')
→ Query rejected: Forbidden keyword or function: 'read_csv'.  (and the DuckDB sandbox blocks it anyway)
```

Full registration + transcript: [`docs/AGENT_ACCESS.md`](docs/AGENT_ACCESS.md).

---

## Architecture — medallion warehouse, one bridge key

```
Spotify API (PKCE, no secret)        YouTube (yt-dlp + ffmpeg)
      │ top tracks/artists ×3 ranges       │ {spotify_track_id}.mp3
      ▼                                     ▼
   STAGING (Bronze) ── append-only snapshots + lineage
      ▼
   CLEANSED (Silver) ── typed, deduped; 77-dim DSP features (librosa)
      ▼
   MODELED (Gold) ── fact_listening_features + dim_{tracks,artists,time_range}
      │                + column_descriptions (agent-readable, exact-verified)
      ▼                    ▼                     ▼
  analysis/ (drift)   search/ (FAISS+UMAP)   agent/ (MCP server over the gold layer)
```

`spotify_track_id` is the **only** join key across metadata, audio filenames, features, and the star schema — the filename *is* the key (no lookup table). Parquet only, `pyarrow` engine.

## What makes it a platform-engineering piece

| Signal | Where |
|---|---|
| **Reproducible env** | `pyproject.toml` + `uv.lock` (pinned graph); `requirements.txt` kept as a pip export |
| **CI / quality gates** | GitHub Actions: `ruff` + `pytest` on every push & PR; 148 synthetic-data tests (no secrets) |
| **Data quality** | deterministic `warehouse-audit` — bridge-key integrity, fact↔dim joins, **exact** feature-contract verification |
| **Agents on data infra** | MCP server with a two-layer security model (SELECT-only guard + a capability-removed DuckDB sandbox) |
| **Scale-ready** | PySpark jobs for the distributed centroid/transform path (`spark/`) |
| **Honest metrics** | drift measured as an effect size (σ-shift), sanity-anchored — see [`notes/engineering_journal.md`](notes/engineering_journal.md) #10 |

## Repo map

```
src/ingestion/   Spotify PKCE auth + fetchers + idempotent YouTube→MP3 acquisition
src/dsp/         librosa 77-dim feature extraction (the layer that replaces the vendor API)
src/warehouse/   medallion transforms: staging → cleansed → modeled (star schema)
src/analysis/    taste-drift engine + σ-normalized trend visuals + insight engine
src/search/      FAISS index + UMAP taste map
src/agent/       MCP server exposing the gold warehouse to AI agents (read-only)
src/export/      single-file HTML portfolio report
spark/           PySpark versions of the warehouse transforms
scripts/         run_pipeline.py + build_{taste_map,insights,trend_charts,report}.py
artifacts/       committed portfolio outputs (taste map, charts, report)
legacy/          archived pre-pipeline v0 (not maintained)
```

## Design docs

- **[`SPEC.md`](SPEC.md)** — approved vision, phase plan (P0–P8), acceptance criteria, decision log.
- **[`notes/PROJECT_CONTEXT.md`](notes/PROJECT_CONTEXT.md)** — verified status + session log.
- **[`CLAUDE_INSTRUCTIONS.md`](CLAUDE_INSTRUCTIONS.md)** — architecture manual + ADRs.

---

*Built by Jordan Vercillo. Portfolio target: Data Engineer – Platform (pipelines at scale, developer experience, data quality, and systems that let AI agents work with data infrastructure).*
