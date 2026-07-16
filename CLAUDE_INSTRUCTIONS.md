# 🎧 Vercillo Analytics — Master Instructions & Roadmap

> **Purpose:** This file is the canonical reference for Claude (AI assistant) when working on this project.  
> It documents architecture decisions, conventions, the current state of the system, and the development roadmap.  
> **Last updated:** 2026-05-06
>
> ⚠️ **Live status has moved to [`notes/PROJECT_CONTEXT.md`](notes/PROJECT_CONTEXT.md)** (2026-07-03).
> This manual stays authoritative for architecture, conventions, and ADRs — but the
> "Current State" table below is a frozen 2026-05-06 snapshot of a pre-upload copy
> (it lists a `webapp/` that is NOT in this repo). Trust PROJECT_CONTEXT for what is
> verified here and now.

---

## 📐 Project Identity

| Field | Value |
|-------|-------|
| **Project** | Vercillo Analytics — Audio Agentic Pipeline |
| **Owner** | Jordan Vercillo |
| **Language** | Python 3.11+ |
| **Domain** | Audio analytics, music taste profiling, temporal drift analysis |
| **Pipeline Runner** | `python scripts/run_pipeline.py` |
| **Web App** | `cd webapp && uvicorn app:app --reload --port 8000` |

---

## 🏗️ Architecture Overview

### Medallion Data Warehouse (Bronze → Silver → Gold)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         MEDALLION ARCHITECTURE                             │
├──────────────────┬────────────────────┬───────────────────────────────────┤
│  STAGING (Bronze) │  CLEANSED (Silver)  │  MODELED (Gold)                   │
│  Raw API dumps    │  Validated & typed   │  Star schema for AI agents        │
│  Raw DSP outputs  │  Deduped & joined    │  Denormalized for query speed     │
├──────────────────┴────────────────────┴───────────────────────────────────┤
│  Bridge Key: spotify_track_id (universal join key across ALL layers)       │
└───────────────────────────────────────────────────────────────────────────┘
```

### Module Map

```
audio-agentic-pipeline/
├── src/
│   ├── ingestion/          # Spotify API + YouTube audio acquisition
│   │   ├── auth.py             # Spotify OAuth (PKCE + client credentials)
│   │   ├── fetchers.py         # API fetchers (top tracks, artists, features)
│   │   ├── audio_downloader.py # YouTube → MP3 download pipeline
│   │   ├── guardrails.py       # API rate limiting + retry logic
│   │   └── serializer.py       # DataFrame → Parquet serialization
│   │
│   ├── dsp/                # Digital Signal Processing (audio features)
│   │   ├── config.py           # DSPConfig dataclass (sample rate, hop, etc.)
│   │   ├── audio_loader.py     # MP3 → AudioSignal (librosa)
│   │   ├── feature_extractor.py # 77-dimensional feature vector extraction
│   │   ├── collection_extractor.py # Batch extraction for real MP3 files
│   │   ├── embedding_extractor.py  # PANNs 2048D deep embeddings (optional)
│   │   └── serializer.py      # Feature serialization to Parquet
│   │
│   ├── warehouse/          # Medallion layers
│   │   ├── staging.py         # Land raw data (no transforms)
│   │   ├── cleansed.py        # Validate, type-cast, deduplicate
│   │   └── modeled.py         # Build star schema (fact + dimensions)
│   │
│   ├── search/             # Vector similarity search (FAISS)
│   │   ├── config.py          # VectorStoreConfig
│   │   ├── faiss_store.py     # FAISS index CRUD operations
│   │   ├── pipeline.py        # End-to-end DAG orchestrator
│   │   └── visualizer.py      # UMAP taste maps
│   │
│   └── analysis/           # Temporal taste analysis
│       ├── drift.py           # Taste drift scores (cosine distance)
│       └── visualizations.py  # Matplotlib temporal plots
│
├── spark/                  # PySpark distributed jobs
│   ├── temporal_aggregate.py  # Distributed centroid computation
│   └── feature_transform.py   # Distributed feature engineering
│
├── webapp/                 # Public-facing web application
│   ├── app.py                 # FastAPI backend + Spotify OAuth
│   ├── templates/index.html   # Dark-themed frontend
│   ├── static/style.css       # CSS (custom properties + responsive grid)
│   ├── Dockerfile             # Container deployment
│   └── requirements.txt       # Webapp-specific deps
│
├── scripts/
│   └── run_pipeline.py        # Full 7-step orchestrator
│
├── data/
│   ├── raw_audio/             # Downloaded MP3s ({track_id}.mp3)
│   └── warehouse/
│       ├── staging/           # Raw Parquet (Bronze)
│       ├── cleansed/          # Validated Parquet (Silver)
│       └── modeled/           # Star schema Parquet (Gold)
│
├── notebooks/                 # Jupyter exploration notebooks
├── requirements.txt           # Project dependencies
├── legacy/PR_REFERENCE.md     # historical PR documentation (Phases 1–4; moved P3.7)
└── CLAUDE_INSTRUCTIONS.md     # ← THIS FILE
```

---

## 🔑 Core Concepts

### 1. Universal Bridge Key

**`spotify_track_id`** is the join key across ALL layers:
- Spotify metadata → warehouse staging
- Audio file naming → `{spotify_track_id}.mp3`
- DSP features → attached via filename stem
- Star schema fact table → composite key with `time_range`

**Never introduce a second ID system.** Everything routes through `spotify_track_id`.

### 2. Feature Vector (77 Dimensions)

The DSP pipeline extracts these feature groups from each track:

| Group | Features | Count |
|-------|----------|-------|
| Tempo | `tempo_bpm` | 1 |
| Energy | `rms_mean`, `rms_std` | 2 |
| Zero Crossing | `zcr_mean`, `zcr_std` | 2 |
| MFCCs | `mfcc_mean_0..12`, `mfcc_std_0..12` | 26 |
| Chroma | `chroma_mean_C..B`, `chroma_std_C..B` | 24 |
| Spectral | `spectral_centroid_mean/std`, `spectral_bandwidth_mean/std`, `spectral_rolloff_mean/std` | 6 |
| Harmonic | `harmonic_ratio` | 1 |
| Tonality | `estimated_key`, `estimated_mode` | 2 |
| **Derived** | `spectral_contrast_mean_0..6` | 7 |
| **Derived** | `spectral_flatness_mean` | 1 |
| **Derived** | Various onset/rhythm features | ~5 |

### 3. Time Ranges (Temporal Windows)

Spotify provides three non-overlapping temporal windows:

| Key | Label | Approximate Window |
|-----|-------|-------------------|
| `short_term` | Last 4 Weeks | ~28 days |
| `medium_term` | Last 6 Months | ~180 days |
| `long_term` | All Time | Account lifetime |

These are the partition keys in the star schema and the basis for drift analysis.

### 4. Star Schema Design

```
              dim_time_range
                    │
    fact_listening_features (composite PK: track_id + time_range)
           │                    │
      dim_tracks           dim_artists
```

The fact table is **intentionally denormalized** — it includes track_name, artist_names, and all 77 features inline. This is agent-optimized: an AI querying "highest-energy track in short_term" gets results without JOINs.

---

## 📏 Conventions & Standards

### Code Style

| Rule | Details |
|------|---------|
| Docstrings | Module-level docstring required. Functions use Google-style. |
| Type Hints | All function signatures must be typed (`-> ReturnType`) |
| Imports | Standard lib → third-party → local. Absolute imports preferred. |
| Logging | `logging.getLogger(__name__)` — never `print()` for operational logs |
| Error Handling | Try/except with specific exceptions. Never bare `except:` |
| Dataclasses | Use `@dataclass` for config/result objects (not dicts) |

### Data Standards

| Rule | Details |
|------|---------|
| Serialization | **Parquet only** — NEVER CSV for feature matrices |
| Engine | `pyarrow` for all Parquet operations |
| Bridge Key | `spotify_track_id` — string, never integer |
| Nulls | Explicit handling — `dropna()` only with documentation |
| Column Naming | `snake_case` always (e.g., `tempo_bpm`, `rms_mean`) |

### Security Standards

| Rule | Details |
|------|---------|
| Credentials | Environment variables only (`SPOTIPY_CLIENT_ID`, etc.) |
| No Hardcoding | Never commit secrets, tokens, or API keys |
| Dependencies | Pin to minimum patched versions (see Security section) |
| Web XSS | Client-side `esc()` + `safeUrl()` allowlisting |
| Cookies | `httponly=True`, `samesite="lax"`, `secure` on HTTPS |

### Testing Conventions

| Rule | Details |
|------|---------|
| Location | `test_*.py` alongside the module (e.g., `src/dsp/test_dsp.py`) |
| Framework | `pytest` with `assert` statements |
| Fixtures | Synthetic data via `generate_test_signal()` — no real API calls |
| Coverage Target | Critical paths: ingestion, DSP, warehouse transforms |

---

## ⚙️ Pipeline Execution

### Full Pipeline

```bash
cd audio-agentic-pipeline
python scripts/run_pipeline.py
```

### Step-by-Step Breakdown

| Step | Function | Module | What it does |
|------|----------|--------|--------------|
| 1 | `step_1_fetch_metadata()` | `src/ingestion/fetchers.py` | Fetch top tracks + artists (3 time ranges) |
| 2 | `step_2_stage_metadata()` | `src/warehouse/staging.py` | Land raw metadata into Staging Parquet |
| 3 | `step_3_download_audio()` | `src/ingestion/audio_downloader.py` | Download MP3s from YouTube (idempotent) |
| 4 | `step_4_extract_features()` | `src/dsp/collection_extractor.py` | Extract 77D features from MP3s |
| 5 | `step_5_stage_features()` | `src/warehouse/staging.py` | Land features into Staging Parquet |
| 6 | `step_6_build_cleansed()` | `src/warehouse/cleansed.py` | Validate, type-cast, deduplicate |
| 7 | `step_7_build_modeled()` | `src/warehouse/modeled.py` | Build star schema (fact + dimensions) |

### CLI Flags

```bash
python scripts/run_pipeline.py --clean           # Clear warehouse only
python scripts/run_pipeline.py --skip-download   # Skip audio download (uses cached MP3s)
python scripts/run_pipeline.py --skip-extract    # Skip DSP extraction (uses cached features)
```

---

## 🔒 Security Requirements

### Dependency Minimums

| Package | Minimum | Reason |
|---------|---------|--------|
| `yt-dlp` | `>=2026.2.21` | Command injection + RCE CVEs |
| `fastapi` | `>=0.115.0` | Security patches |
| `python-multipart` | `>=0.0.22` | Multipart parsing vulnerability |

### Web Application Security

- **No hardcoded credentials** — env vars + startup warning
- **Session rotation** on OAuth callback (prevents session fixation)
- **Rate limiting** — 1 request per 10 seconds per session
- **URL allowlisting** — only `open.spotify.com` and `i.scdn.co` domains pass `safeUrl()`
- **Secure cookies** — `httponly`, `samesite=lax`, `secure` auto-detected

---

## 🗺️ Development Roadmap

### ✅ Completed

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1** | Audio Acquisition Layer (YouTube → MP3) | ✅ Complete |
| **Phase 2** | Real Audio Feature Extraction (DSP batch) | ✅ Complete |
| **Phase 3** | Full Pipeline Orchestration (7-step runner) | ✅ Complete |
| **Phase 4** | Public-Facing Web Application (FastAPI) | ✅ Complete |

### 🔜 Phase 5 — Insight Engine & Advanced Analytics

| Item | Description | Priority | Complexity |
|------|-------------|----------|-----------|
| **5.1** | Automated Insight Narrative Generation | High | Medium |
| **5.2** | Genre Clustering (FAISS + UMAP on real embeddings) | High | Medium |
| **5.3** | Temporal Trend Visualizations (interactive plots) | Medium | Low |
| **5.4** | Portfolio Export (static HTML report) | Medium | Low |

#### 5.1 — Insight Engine (Narrative Generation)

**Goal:** Auto-generate a written narrative about the user's taste profile.

```
Input:  Star schema fact table + drift metrics
Output: Markdown narrative (e.g., "Your taste has shifted 23% toward
        higher-energy electronic music over the past 6 months...")
```

**Approach:**
- Load modeled star schema
- Compute drift scores (existing `drift.py`)
- Template-based narrative with LLM enhancement (optional)
- Output as structured Markdown or JSON

**Key Files to Modify:**
- New: `src/analysis/insights.py`
- Touches: `src/analysis/drift.py` (import drift scores)
- Touches: `scripts/run_pipeline.py` (add step 8)

#### 5.2 — Genre Clustering

**Goal:** Cluster tracks by acoustic similarity and visualize genre neighborhoods.

```
Input:  77D feature vectors from fact_listening_features
Output: UMAP 2D projection + cluster assignments + taste map visualization
```

**Approach:**
- Use existing `src/search/faiss_store.py` for index building
- Use existing `src/search/visualizer.py` for UMAP + plotting
- Add genre label overlay from `dim_artists.genres`
- Optionally enhance with PANNs 2048D embeddings

**Key Files to Modify:**
- Enhance: `src/search/pipeline.py` (add clustering step)
- Enhance: `src/search/visualizer.py` (genre-colored taste map)
- New: `src/analysis/clustering.py` (k-means or HDBSCAN)

#### 5.3 — Temporal Trend Visualizations

**Goal:** Interactive charts showing how taste metrics change over time ranges.

```
Input:  Drift metrics + temporal centroids
Output: Matplotlib/Plotly charts (radar, line, heatmap)
```

**Chart Types:**
1. **Radar chart** — Feature profile per time range (overlay 3 polygons)
2. **Heatmap** — Feature × time_range matrix (show what changed most)
3. **Bar chart** — Top-5 features with largest drift
4. **Timeline** — Energy/tempo trend across short→medium→long

**Key Files to Modify:**
- Enhance: `src/analysis/visualizations.py` (new chart functions)
- New: `webapp/templates/dashboard.html` (if web-based)

#### 5.4 — Portfolio Export

**Goal:** Generate a standalone HTML report summarizing the user's musical profile.

```
Input:  All outputs (narrative, charts, top items, drift scores)
Output: Single-page static HTML (sharable, no server required)
```

**Approach:**
- Jinja2 template with embedded CSS + SVG charts
- Inline all assets (single `.html` file)
- Include: top tracks, drift summary, taste map, narrative

**Key Files to Modify:**
- New: `src/export/portfolio.py`
- New: `src/export/templates/portfolio.html`

---

### 🔮 Phase 6 — Production & Scale (Future)

| Item | Description |
|------|-------------|
| **6.1** | Redis session store (replace in-memory dict) |
| **6.2** | Scheduled pipeline runs (cron/Airflow/Cloud Functions) |
| **6.3** | Multi-user support (user-scoped warehouse partitions) |
| **6.4** | CI/CD pipeline (GitHub Actions: lint, test, deploy) |
| **6.5** | Cloud deployment (GCP Cloud Run or Railway) |
| **6.6** | PANNs embedding integration (2048D deep features) |
| **6.7** | Real-time drift tracking (webhook on playlist changes) |

---

## 🧠 Context for Claude

### When Working on This Codebase:

1. **Always use absolute paths** — the project root is `audio-agentic-pipeline/`
2. **Never break the bridge key** — `spotify_track_id` connects everything
3. **Parquet only** — never suggest CSV for feature data
4. **Check idempotency** — downloads and extractions should skip if already done
5. **Security first** — no hardcoded secrets, pin dependency versions
6. **Test with synthetic data** — never require real API calls for unit tests
7. **Preserve the module structure** — each `src/` subdirectory is a cohesive layer

### When Adding New Features:

1. **Start from the modeled layer** — what does the star schema need?
2. **Work backward** — modeled ← cleansed ← staging ← raw
3. **Add to `run_pipeline.py`** — new steps go at the end of the orchestrator
4. **Update `__init__.py`** — export all public functions
5. **Follow existing patterns** — look at how similar modules work first
6. **Add type hints and docstrings** — no exceptions

### When Fixing Bugs:

1. **Check the data flow** — trace from API/file → staging → cleansed → modeled
2. **Verify bridge key** — is `spotify_track_id` present and consistent?
3. **Check Parquet schema** — column types must match expected schema
4. **Look at the test file** — each module has `test_*.py` with examples

### Quick Reference Commands:

```bash
# Run full pipeline
python scripts/run_pipeline.py

# Run pipeline without audio (metadata-only testing)
python scripts/run_pipeline.py --skip-download --skip-extract

# Clean and rebuild warehouse
python scripts/run_pipeline.py --clean
python scripts/run_pipeline.py

# Run webapp locally
cd webapp && uvicorn app:app --reload --port 8000

# Run tests
pytest src/dsp/test_dsp.py -v
pytest src/ingestion/test_ingestion.py -v
pytest src/search/test_search.py -v

# PySpark job (local mode)
python spark/temporal_aggregate.py
```

---

## 📚 Key Design Decisions (ADRs)

### ADR-001: Medallion Architecture
**Decision:** Use Staging → Cleansed → Modeled (Bronze → Silver → Gold).  
**Rationale:** Clear separation of concerns. Raw data is immutable. Transforms are repeatable. Modeled layer is query-optimized.

### ADR-002: Denormalized Fact Table
**Decision:** Include track_name, artist_names in fact table (not just IDs).  
**Rationale:** Agent-optimized. An AI agent should get complete results from a single table scan. Storage overhead is negligible at our scale.

### ADR-003: Cosine Distance for Drift
**Decision:** Use cosine distance (not Euclidean) for taste drift scores.  
**Rationale:** Audio features span different scales (tempo 60-200 vs RMS 0-1). Cosine measures angle, making it scale-invariant.

### ADR-004: File-Based Idempotency
**Decision:** Skip downloads/extractions if output files or Parquet records already exist.  
**Rationale:** Pipeline is meant to run repeatedly (new listening data arrives). Re-downloading or re-extracting unchanged tracks wastes time and risks rate limits.

### ADR-005: spotify_track_id as Filename
**Decision:** Name MP3 files `{spotify_track_id}.mp3`.  
**Rationale:** No lookup table needed. The file's name IS the bridge key. Any file in `raw_audio/` can be directly joined to metadata via filename stem.

### ADR-006: Parquet-Only Persistence
**Decision:** Never use CSV for feature matrices or warehouse layers.  
**Rationale:** Parquet preserves types (float64 precision), supports columnar reads (fast feature selection), and compresses well (77 columns × thousands of rows).

---

## 🚦 Current State (as of 2026-05-06)

| Component | Status | Notes |
|-----------|--------|-------|
| Spotify ingestion | ✅ Working | Auth, fetchers, serialization |
| Audio download | ✅ Working | yt-dlp with rate limiting |
| DSP extraction | ✅ Working | 77D features from real MP3s |
| Warehouse (Staging) | ✅ Working | Raw Parquet landing |
| Warehouse (Cleansed) | ✅ Working | Validated + deduped |
| Warehouse (Modeled) | ✅ Working | Star schema |
| FAISS vector search | ✅ Working | Similarity queries |
| Drift analysis | ✅ Working | Cosine distance metrics |
| PySpark aggregation | ✅ Working | Distributed centroids |
| Web application | ✅ Working | FastAPI + OAuth + frontend |
| Insight engine | ❌ Not started | Phase 5.1 |
| Genre clustering | ❌ Not started | Phase 5.2 |
| Trend visualizations | ❌ Not started | Phase 5.3 |
| Portfolio export | ❌ Not started | Phase 5.4 |

---

*This file should be updated as new phases are completed or new decisions are made.*