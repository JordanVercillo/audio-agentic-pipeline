# Pull Request: Temporal Audio Pipeline — Expansion (Phases 1–4)

**Branch:** `copilot/build-temporal-audio-pipeline`  
**Target:** `main`  
**Status:** Ready for Review  

---

## 📋 Summary

Implements the full Temporal Audio Pipeline expansion roadmap (Phases 1–4):

1. **Phase 1 — Audio Acquisition Layer** (`src/ingestion/audio_downloader.py`)
2. **Phase 2 — Real Audio Feature Extraction** (`src/dsp/collection_extractor.py`)
3. **Phase 3 — Full Pipeline Orchestration** (`scripts/run_pipeline.py`)
4. **Phase 4 — Public-Facing Web Application** (`webapp/`)

Plus security hardening (XSS, cookies, credentials).

---

## 📊 Diff Stats

```
 11 files changed, 1749 insertions(+), 32 deletions(-)
```

| File | Changes |
|------|---------|
| `src/ingestion/audio_downloader.py` | **+503** (new) |
| `webapp/app.py` | **+316** (new) |
| `webapp/static/style.css` | **+308** (new) |
| `src/dsp/collection_extractor.py` | **+230** (new) |
| `scripts/run_pipeline.py` | **+167/-32** (rewrite) |
| `webapp/templates/index.html` | **+172** (new) |
| `webapp/Dockerfile` | **+16** (new) |
| `src/ingestion/__init__.py` | **+14** |
| `requirements.txt` | **+9** |
| `src/dsp/__init__.py` | **+8** |
| `webapp/requirements.txt` | **+6** (new) |

---

## 🔀 Commits

| # | Message |
|---|---------|
| 1 | `feat: add audio downloader (Phase 1) and collection extractor (Phase 2)` |
| 2 | `feat: add full pipeline orchestration (Phase 3) and web app (Phase 4)` |
| 3 | `fix: address security findings — XSS escaping, cookie security, credential handling` |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    run_pipeline.py (Orchestrator)                 │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│ Step 1   │ Step 2   │ Step 3   │ Step 4   │ Step 5-6 │ Step 7   │
│ Fetch    │ Stage    │ Download │ Extract  │ Cleansed │ Modeled  │
│ Spotify  │ Metadata │ Audio    │ Features │ Layer    │ Star     │
│ API      │          │ (yt_dlp) │ (DSP)    │          │ Schema   │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
         ↓                    ↓                    ↓
 data/warehouse/        data/raw_audio/      data/warehouse/
   staging/            {track_id}.mp3         modeled/
```

---

## 📁 New Files

### Phase 1: `audio-agentic-pipeline/src/ingestion/audio_downloader.py`

```python
"""
audio_downloader.py — YouTube Audio Acquisition Layer
======================================================
Downloads MP3 audio from YouTube for Spotify tracks, bridging the gap
between Spotify metadata and real audio files for local DSP extraction.

Architecture:
    1. YouTube Search Resolver: track_name + artist_name → YouTube URL
    2. MP3 Downloader: URL → data/raw_audio/{spotify_track_id}.mp3
    3. Rate Limit Guardrails: randomized throttling + exponential backoff
    4. Idempotent Skip Logic: file-system + Parquet feature cache check
    5. Batch Orchestrator: download_audio_for_tracks(tracks_df) → summary
"""

import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import yt_dlp

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_AUDIO_DIR = _PROJECT_ROOT / "data" / "raw_audio"
CLEANSED_FEATURES_PATH = (
    _PROJECT_ROOT / "data" / "warehouse" / "cleansed" / "cleansed_features.parquet"
)

logger = logging.getLogger(__name__)


@dataclass
class DownloadConfig:
    """Configuration for YouTube audio downloads with rate limiting."""
    output_dir: Union[str, Path] = RAW_AUDIO_DIR
    min_delay: float = 5.0
    max_delay: float = 30.0
    error_delay: float = 30.0
    rate_limit_delay: float = 60.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    prefer_official: bool = True


# ── Rate Limit Guardrails ──

def _random_delay(min_sec: float = 5.0, max_sec: float = 30.0) -> None:
    """Sleep for a random duration (uniform distribution)."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def _exponential_backoff(attempt: int, base_delay: float = 30.0, 
                         factor: float = 2.0, max_delay: float = 300.0) -> None:
    """Exponential backoff with jitter for retry scenarios."""
    delay = min(base_delay * (factor ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.25)
    time.sleep(delay + jitter)


# ── Idempotent Skip Logic ──

def _audio_file_exists(spotify_track_id: str, output_dir) -> bool:
    """Check if the MP3 file already exists on disk."""
    path = Path(output_dir) / f"{spotify_track_id}.mp3"
    return path.exists() and path.stat().st_size > 0


def _features_already_extracted(spotify_track_id: str, features_path) -> bool:
    """Check if DSP features already exist in the cleansed Parquet."""
    # ... reads parquet and checks for track_id ...


def get_cached_track_ids(features_path=CLEANSED_FEATURES_PATH) -> set:
    """Load set of track_ids with existing features (batch optimization)."""
    # ... reads parquet column for batch skip logic ...


# ── YouTube Search Resolver ──

def resolve_youtube_url(track_name: str, artist_name: str, 
                        prefer_official: bool = True) -> Optional[str]:
    """Search YouTube via yt_dlp and return best-matching video URL."""
    query = f"{artist_name} {track_name}"
    if prefer_official:
        query += " official audio"
    
    ydl_opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": False, "noplaylist": True,
        "default_search": "ytsearch1",
    }
    # Uses ytsearch1:{query} to get single best result
    # Returns webpage_url from first entry


# ── MP3 Downloader ──

def download_track_audio(youtube_url: str, spotify_track_id: str, 
                         output_dir=RAW_AUDIO_DIR) -> Optional[str]:
    """Download audio as MP3 using bestaudio/best format + FFmpeg postprocessor."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / f"{spotify_track_id}.%(ext)s"),
        "quiet": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    # Downloads and returns path, or None on failure


def download_single_track(track_name, artist_name, spotify_track_id, 
                          config=None) -> dict:
    """Full pipeline: search → resolve → download with retry."""
    # Includes idempotent skip, retry with exponential backoff
    # Returns: {spotify_track_id, status, audio_path, error}


# ── Batch Orchestrator ──

def download_audio_for_tracks(tracks_df: pd.DataFrame, config=None, 
                              skip_if_features_exist=True) -> pd.DataFrame:
    """
    Download audio for all tracks in a DataFrame.
    
    - Deduplicates by spotify_track_id
    - Pre-loads feature cache for batch efficiency
    - Randomized throttling between downloads
    - Returns summary DataFrame with status per track
    """
```

---

### Phase 2: `audio-agentic-pipeline/src/dsp/collection_extractor.py`

```python
"""
collection_extractor.py — Batch Feature Extraction for Real Audio
==================================================================
Runs the existing DSP pipeline on real downloaded MP3 files.

Key Responsibilities:
    1. Load each MP3 from data/raw_audio/ using existing audio_loader
    2. Extract features via existing DSP pipeline
    3. Attach spotify_track_id bridge key (derived from filename)
    4. Cache results — skip if already in cleansed Parquet
    5. Handle errors gracefully — log failures, continue batch
"""

import logging
import random
import time
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from .audio_loader import load_audio, AudioSignal
from .config import DSPConfig
from .feature_extractor import TrackFeatures, extract_features

logger = logging.getLogger(__name__)


def _load_cached_feature_ids(features_path) -> set:
    """Load set of track_ids with existing features (idempotency layer 2)."""


def extract_features_for_track(audio_path, spotify_track_id=None, 
                               config=None) -> Optional[dict]:
    """
    Extract DSP features from a single MP3 file.
    
    Track ID derived from filename ({spotify_track_id}.mp3).
    Returns dict suitable for DataFrame row, or None on error.
    """
    signal = load_audio(audio_path, config=config)
    features = extract_features(signal, config=config)
    row = features.to_summary_dict()
    row["spotify_track_id"] = spotify_track_id
    return row


def extract_features_for_collection(tracks_df=None, audio_dir=RAW_AUDIO_DIR,
                                     config=None, skip_if_cached=True,
                                     min_delay=0.0, max_delay=0.0) -> pd.DataFrame:
    """
    Batch extract DSP features for all MP3 files.
    
    - Discovers MP3 files in raw_audio/
    - Filters to tracks_df if provided
    - Skips tracks with existing features in cache
    - Wraps each extraction in try/except for resilience
    - Returns DataFrame with all features + spotify_track_id
    """
```

---

### Phase 3: `audio-agentic-pipeline/scripts/run_pipeline.py` (Rewritten)

```python
"""
run_pipeline.py — Full Temporal Audio Pipeline Runner
======================================================
Orchestrates the complete data pipeline end-to-end:

    1. Fetch Spotify metadata (top tracks + artists, all time ranges)
    2. Download audio from YouTube (with idempotent skip logic)
    3. Extract DSP features from real MP3 files
    4. Build Medallion warehouse (Staging → Cleansed → Modeled)

Usage:
    python scripts/run_pipeline.py           # full pipeline
    python scripts/run_pipeline.py --clean   # clear warehouse only
    python scripts/run_pipeline.py --skip-download  # skip audio download
    python scripts/run_pipeline.py --skip-extract   # skip feature extraction
"""

# 7 orchestrated steps:
#   step_1_fetch_metadata()     → fetch_all_top_items()
#   step_2_stage_metadata()     → land_staging_tracks/artists()
#   step_3_download_audio()     → download_audio_for_tracks()
#   step_4_extract_features()   → extract_features_for_collection()
#   step_5_stage_features()     → land_staging_features()
#   step_6_build_cleansed()     → build_cleansed_tracks/features()
#   step_7_build_modeled()      → build_star_schema()
```

---

### Phase 4: `audio-agentic-pipeline/webapp/`

#### `webapp/app.py` — FastAPI Backend

```python
"""
app.py — Spotify Top Items Web Application
=============================================
FastAPI web app: Spotify OAuth → top 3 tracks/artists × 3 time ranges.

Features:
    - Spotify PKCE OAuth web redirect flow
    - In-memory session-based caching (5 min TTL)
    - Per-session rate limiting (1 request per 10 seconds)
    - Dark-themed responsive frontend
    - No audio downloading for web users (metadata only)
    - Secure cookies (httponly, samesite=lax, secure on HTTPS)
    - XSS protection via client-side escaping + URL allowlisting

Endpoints:
    GET /           → Landing page (login or results)
    GET /login      → Redirect to Spotify OAuth
    GET /callback   → OAuth callback, exchange code for tokens
    GET /api/top-items → JSON: top 3 tracks + artists per time range
    GET /logout     → Clear session
"""

# Key security measures:
# - Credentials from env vars only (no hardcoded secrets)
# - Session rotation on OAuth callback (prevents fixation)
# - COOKIE_SECURE auto-detected from REDIRECT_URI scheme
# - Rate limiting per session (10s cooldown)
# - Cache TTL (5 min) to avoid redundant Spotify API calls
```

#### `webapp/templates/index.html` — Frontend

- Dark-themed single page with 3 columns (Last 4 Weeks / Last 6 Months / All Time)
- Top 3 tracks + top 3 artists per time range
- Album art, track name, artist name
- XSS escaping via `esc()` helper and `safeUrl()` URL allowlisting
- Mobile-responsive grid layout
- Spotify branding with gradient header

#### `webapp/static/style.css` — Dark Theme (308 lines)

- CSS custom properties for theming
- Card-based layout with hover effects
- Responsive 3-column grid (collapses to single on mobile)
- Spotify green accent color + purple accent glow
- Loading spinner and error states

#### `webapp/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### `webapp/requirements.txt`

```
fastapi>=0.115.0
uvicorn>=0.24.0
jinja2>=3.1.0
spotipy>=2.23.0
python-multipart>=0.0.22
```

---

## 📦 Dependency Changes (`requirements.txt`)

```diff
+# ── YouTube Audio Acquisition (yt_dlp for downloading audio) ──
+yt-dlp>=2026.2.21
+
+# ── Web Application ──
+fastapi>=0.115.0
+uvicorn>=0.24.0
+jinja2>=3.1.0
+python-multipart>=0.0.22
```

> **Security Note:** `yt-dlp>=2026.2.21` addresses CVE command injection and RCE vulnerabilities. `python-multipart>=0.0.22` and `fastapi>=0.115.0` address known security patches.

---

## 🔐 Security Measures

| Area | Implementation |
|------|---------------|
| **XSS Prevention** | Client-side `esc()` text escaping + `safeUrl()` allowlisting (only `https://open.spotify.com/` and `https://i.scdn.co/` domains) |
| **Cookie Security** | `httponly=True`, `samesite="lax"`, `secure` auto-detected from HTTPS |
| **Session Fixation** | Session ID rotated on OAuth callback (never reflects user input) |
| **Credential Handling** | Environment variables only; warns if not set; no hardcoded secrets |
| **Rate Limiting** | Per-session: 1 request per 10 seconds; cache TTL: 5 minutes |
| **Dependency Versions** | All pinned to patched versions addressing known CVEs |

---

## 🧪 How to Test

### Pipeline (Phases 1–3)
```bash
cd audio-agentic-pipeline

# Full pipeline (requires Spotify auth + ffmpeg)
python scripts/run_pipeline.py

# Skip audio download (metadata only)
python scripts/run_pipeline.py --skip-download --skip-extract

# Clean warehouse
python scripts/run_pipeline.py --clean
```

### Web App (Phase 4)
```bash
cd audio-agentic-pipeline/webapp

# Set environment variables
export SPOTIPY_CLIENT_ID="your_client_id"
export SPOTIPY_CLIENT_SECRET="your_client_secret"
export SPOTIPY_REDIRECT_URI="http://127.0.0.1:8000/callback"

# Run locally
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# Or via Docker
docker build -t vercillo-webapp .
docker run -p 8000:8000 \
  -e SPOTIPY_CLIENT_ID=... \
  -e SPOTIPY_CLIENT_SECRET=... \
  vercillo-webapp
```

---

## ✅ Checklist

- [x] Phase 1: Audio Acquisition Layer (`audio_downloader.py`)
  - [x] YouTube Search Resolver (yt_dlp ytsearch1)
  - [x] MP3 Downloader with bridge key filename
  - [x] Randomized throttling (5–30s uniform)
  - [x] Exponential backoff on errors
  - [x] Idempotent skip logic (file + Parquet cache)
  - [x] Batch orchestrator with progress reporting
- [x] Phase 2: Real Audio Feature Extraction (`collection_extractor.py`)
  - [x] End-to-end extraction function
  - [x] Feature cache in cleansed Parquet
  - [x] Error resilience (try/except per track)
- [x] Phase 3: Full Pipeline Script (`run_pipeline.py`)
  - [x] 7-step orchestration
  - [x] CLI flags (--clean, --skip-download, --skip-extract)
  - [x] Warehouse summary reporting
- [x] Phase 4: Web Application (`webapp/`)
  - [x] FastAPI backend with Spotify OAuth
  - [x] API endpoint (top 3 tracks + artists × 3 time ranges)
  - [x] Dark-themed responsive frontend
  - [x] Rate limiting + caching
  - [x] Dockerfile for deployment
- [x] Security hardening
  - [x] XSS escaping + URL allowlisting
  - [x] Secure cookie configuration
  - [x] No hardcoded credentials
  - [x] Session rotation on callback
  - [x] Patched dependency versions

---

## 🔮 Remaining (Phase 5 — Future)

- [ ] 5.1 Insight Engine (automated narrative generation)
- [ ] 5.2 Genre Clustering (FAISS + UMAP on real embeddings)
- [ ] 5.3 Temporal Trend Visualizations
- [ ] 5.4 Portfolio Export (static HTML)