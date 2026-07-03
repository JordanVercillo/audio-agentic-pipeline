"""
build_temporal_analysis.py — Generates the Temporal Analysis Notebook
======================================================================
The main portfolio deliverable: end-to-end taste drift analysis
using the Medallion warehouse and temporal DSP features.

Run: python notebooks/build_temporal_analysis.py
"""

from pathlib import Path
import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

OUTPUT_PATH = Path(__file__).resolve().parent / "temporal_analysis.ipynb"

def md(text):
    return new_markdown_cell(text.strip())

def code(text):
    return new_code_cell(text.strip())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def section_header():
    return [
        md("""
# 🎧 Temporal Audio Pipeline — How Your Music Taste Evolves

**Author:** Jordan Vercillo
**Last Updated:** May 2026
**Repository:** `audio-agentic-pipeline/`

---

## Project Overview

This notebook analyzes **how musical taste evolves over time** by comparing Spotify listening history across three temporal windows:

| Window | Spotify Label | Approximate Coverage |
|---|---|---|
| **Recent** | `short_term` | Last ~4 weeks |
| **Medium** | `medium_term` | Last ~6 months |
| **Historical** | `long_term` | Several years |

### Pipeline Architecture (Medallion)

```
Spotify API ──→ Staging (Raw) ──→ Cleansed (Typed) ──→ Modeled (Star Schema)
                                                              │
Audio Files ──→ DSP (77D) ──────────────────────────→ fact_listening_features
                                                              │
                                                     Analysis & Visualization
                                                     ├── Taste Drift Score
                                                     ├── Temporal Centroids
                                                     ├── Feature Deltas
                                                     └── UMAP Taste Maps
```

### Key Metric: Taste Drift Score

The **cosine distance** between your short-term and long-term acoustic centroids.

| Score Range | Interpretation |
|---|---|
| 0.00 – 0.05 | Minimal drift — stable taste, comfort zone |
| 0.05 – 0.15 | Moderate drift — exploring new sounds |
| 0.15 – 0.30 | Significant drift — taste actively evolving |
| 0.30+ | Major drift — genre shift or discovery phase |
"""),
    ]


def section_setup():
    return [
        md("""
---
## Section 1: Setup & Configuration
"""),
        code("""
import sys, os, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Project root
PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore", category=UserWarning, module="librosa")
warnings.filterwarnings("ignore", category=UserWarning, module="umap")
warnings.filterwarnings("ignore", category=FutureWarning)

# Pipeline modules
from src.dsp import generate_test_signal, extract_features, AudioSignal, SAMPLE_RATE
from src.warehouse.staging import land_staging_tracks, land_staging_features
from src.warehouse.cleansed import build_cleansed_tracks, build_cleansed_features
from src.warehouse.modeled import build_star_schema, load_fact_table, get_column_descriptions, COLUMN_DESCRIPTIONS
from src.analysis.drift import compute_taste_drift, compute_temporal_centroids, DRIFT_FEATURE_COLS, FEATURE_LABELS
from src.analysis.visualizations import (
    plot_drift_radar, plot_temporal_heatmap,
    plot_umap_by_time_range, plot_genre_flow,
    plot_feature_distributions,
)

print(f"Project root: {PROJECT_ROOT}")
print(f"Python: {sys.version.split()[0]}")
print("✅ All modules loaded successfully")
"""),
        md("""
### Configuration

Set `USE_LIVE_DATA = True` to analyze **your actual Spotify listening history**.
Set `USE_LIVE_DATA = False` (default) for the synthetic demo — no credentials needed.

> **Live data requirements:**
> 1. Your Spotify account must be registered in the app's [Developer Dashboard](https://developer.spotify.com/dashboard)
> 2. On first run, a browser window opens for Spotify login (PKCE auth)
> 3. Works with any Spotify tier (Free or Premium)
> 4. DSP features are generated synthetically — acoustic analysis of your real listening patterns
"""),
        code("""
# ━━━ DATA SOURCE CONFIGURATION ━━━
# True  → Fetches YOUR top tracks from Spotify across all 3 time ranges.
#          Requires a registered Spotify account (opens browser for auth).
# False → Uses realistic synthetic data (no credentials needed).

USE_LIVE_DATA = False

print(f"Data source: {'🟢 LIVE Spotify API' if USE_LIVE_DATA else '🔵 Synthetic demo data'}")
"""),
    ]


def section_data_generation():
    return [
        md("""
---
## Section 2: Data Acquisition

This section either fetches your **real Spotify listening history** or generates
realistic synthetic data, depending on `USE_LIVE_DATA` above.

Both paths produce the same schema — the rest of the pipeline doesn't care
whether the data is real or synthetic.
"""),
        code("""
if USE_LIVE_DATA:
    # ── LIVE: Fetch from Spotify API ──
    from src.ingestion import get_user_spotify
    from src.ingestion.fetchers import fetch_all_top_items

    print("🔐 Authenticating with Spotify (opens browser on first run)...")
    sp = get_user_spotify()

    # Fetch profile
    me = sp.me()
    print(f"   ✅ Authenticated as: {me.get('display_name', 'Unknown')} ({me['id']})")
    print(f"   Account type: {me.get('product', 'unknown')}")

    # Fetch top tracks + artists across all 3 time ranges
    data = fetch_all_top_items(sp=sp)
    tracks_df = data["tracks"]

    if tracks_df.empty:
        raise RuntimeError(
            "No tracks returned from Spotify API. "
            "Make sure your account is registered in the app's Developer Dashboard."
        )

    print(f"\\n📊 Fetched {len(tracks_df)} track records from your Spotify history")
    print(f"   Time ranges: {tracks_df['time_range'].value_counts().to_dict()}")
    print(f"   Unique tracks: {tracks_df['spotify_track_id'].nunique()}")

else:
    # ── SYNTHETIC: Generate demo data ──
    print("🔵 Generating synthetic Spotify metadata...")
    np.random.seed(42)

    short_artists = ["Dua Lipa", "Bad Bunny", "Charli XCX", "Fred Again..", "Peggy Gou"]
    medium_artists = ["Tame Impala", "Frank Ocean", "SZA", "Tyler, the Creator", "Khruangbin"]
    long_artists = ["Radiohead", "Bon Iver", "Fleet Foxes", "Sufjan Stevens", "Nick Drake"]

    def make_tracks(time_range, artists, n=15):
        records = []
        for i in range(n):
            artist = artists[i % len(artists)]
            records.append({
                "spotify_track_id": f"synth_{time_range}_{i:03d}",
                "track_name": f"{artist} - Track {i+1}",
                "artist_names": artist,
                "artist_ids": f"artist_{artist.lower().replace(' ', '_')}",
                "primary_artist_name": artist,
                "primary_artist_id": f"artist_{artist.lower().replace(' ', '_')}",
                "album_name": f"{artist} Album",
                "album_id": f"album_{time_range}_{i:03d}",
                "album_type": "album",
                "album_release_date": "2025-01-01",
                "duration_ms": int(np.random.uniform(180000, 360000)),
                "explicit": bool(np.random.random() > 0.7),
                "is_local": False,
                "disc_number": 1,
                "track_number": i + 1,
                "num_artists": 1,
                "time_range": time_range,
                "rank": i + 1,
                "isrc": f"US{time_range[:2].upper()}{i:06d}",
                "external_url": f"https://open.spotify.com/track/synth_{time_range}_{i:03d}",
                "preview_url": None,
            })
        return records

    all_records = []
    all_records.extend(make_tracks("short_term",  short_artists,  n=15))
    all_records.extend(make_tracks("medium_term", medium_artists, n=15))
    all_records.extend(make_tracks("long_term",   long_artists,   n=15))

    # Add 5 overlapping tracks for dedup testing
    for i in range(5):
        overlap = all_records[i].copy()
        overlap["time_range"] = "long_term"
        overlap["rank"] = 40 + i
        all_records.append(overlap)

    tracks_df = pd.DataFrame(all_records)
    print(f"   Generated {len(tracks_df)} track records")
    print(f"   Time ranges: {tracks_df['time_range'].value_counts().to_dict()}")
    print(f"   Unique tracks: {tracks_df['spotify_track_id'].nunique()}")
    print(f"   Overlapping tracks: {len(tracks_df) - tracks_df['spotify_track_id'].nunique()}")
"""),
        md("""
### 2.2 — DSP Feature Extraction

We generate acoustic features for each unique track using synthetic audio signals.
The frequency profile is varied by time range to create measurable drift:
- **Short-term** → higher frequencies (brighter, more energetic)
- **Long-term** → lower frequencies (warmer, more acoustic)

> When `USE_LIVE_DATA = True`, the features are still synthetic (keyed to your real track IDs)
> because Spotify's `preview_url` is often unavailable. The pipeline schema and drift analysis
> work identically — the warehouse joins on `spotify_track_id` regardless of feature source.
"""),
        code("""
# ── Generate DSP features (synthetic audio, keyed to real or synthetic track IDs) ──
np.random.seed(42)
feature_records = []
unique_tracks = tracks_df.drop_duplicates(subset=["spotify_track_id"])

for _, row in unique_tracks.iterrows():
    tr = row["time_range"]

    # Frequency profile by time range → creates measurable drift
    if tr == "short_term":
        freq = np.random.uniform(800, 2000)
    elif tr == "medium_term":
        freq = np.random.uniform(400, 900)
    else:
        freq = np.random.uniform(100, 500)

    sig = generate_test_signal(frequency_hz=freq, duration_sec=2.0)
    sig.file_name = row["spotify_track_id"]
    feat = extract_features(sig)
    feat_dict = feat.to_summary_dict()
    feat_dict["spotify_track_id"] = row["spotify_track_id"]
    feat_dict["file_name"] = sig.file_name
    feature_records.append(feat_dict)

features_df = pd.DataFrame(feature_records)
print(f"\\nExtracted features for {len(features_df)} unique tracks")
print(f"Feature dimensions: {len(features_df.select_dtypes(include=[np.number]).columns)}")
"""),
    ]


def section_medallion():
    return [
        md("""
---
## Section 3: Medallion Architecture — Staging → Cleansed → Modeled

Now we run the data through the full warehouse pipeline.
This is the core data engineering demonstration.
"""),
        md("""
### 3.1 — Staging Layer (Bronze)

Raw data lands exactly as received, with lineage metadata for auditability.
"""),
        code("""
# ── STAGING: Land raw data with lineage ──
from src.warehouse.staging import land_staging_tracks, land_staging_features, list_staging_files

STAGING_DIR = PROJECT_ROOT / "data" / "warehouse" / "staging"

tracks_path = land_staging_tracks(tracks_df, output_dir=STAGING_DIR, snapshot_label="demo_run_1")
features_path = land_staging_features(features_df, output_dir=STAGING_DIR, snapshot_label="demo_run_1")

print("\\n📋 Staging Inventory:")
inventory = list_staging_files(STAGING_DIR)
print(inventory.to_string(index=False))
"""),
        md("""
### 3.2 — Cleansed Layer (Silver)

Deduplication, type enforcement, null handling, and schema validation.
"""),
        code("""
# ── CLEANSED: Dedup + type enforcement ──
CLEANSED_DIR = PROJECT_ROOT / "data" / "warehouse" / "cleansed"

cleansed_tracks = build_cleansed_tracks(staging_dir=STAGING_DIR, output_dir=CLEANSED_DIR)
print()
cleansed_features = build_cleansed_features(staging_dir=STAGING_DIR, output_dir=CLEANSED_DIR)
"""),
        md("""
### 3.3 — Modeled Layer (Gold) — Star Schema

The final analytical layer: a denormalized fact table joined with dimension tables,
plus agent-readable column descriptions.
"""),
        code("""
# ── MODELED: Star schema ──
MODELED_DIR = PROJECT_ROOT / "data" / "warehouse" / "modeled"

star = build_star_schema(cleansed_dir=CLEANSED_DIR, output_dir=MODELED_DIR)

# Show the fact table
print("\\n📊 Fact Table Sample (first 5 rows):")
fact = star["fact"]
display_cols = ["spotify_track_id", "track_name", "time_range", "rank",
                "tempo_bpm", "rms_mean", "spectral_centroid_mean", "harmonic_ratio"]
available = [c for c in display_cols if c in fact.columns]
print(fact[available].head().to_string(index=False))
"""),
        code("""
# ── Agent Interface: Column Descriptions ──
print("\\n🤖 Agent-Readable Column Descriptions (sample):\\n")
desc = get_column_descriptions(MODELED_DIR)
for col in ["tempo_bpm", "rms_mean", "harmonic_ratio", "time_range", "rank"]:
    if col in desc:
        print(f"  {col}:")
        print(f"    → {desc[col]}\\n")
"""),
    ]


def section_drift_analysis():
    return [
        md("""
---
## Section 4: Taste Drift Analysis

The core analytical payload. We compute how the user's acoustic taste
evolves across the three temporal windows.
"""),
        md("""
### 4.1 — Temporal Centroids

The acoustic centroid is the **mean feature vector** per time range.
It represents the "average sound" of the user's listening for that window.
"""),
        code("""
# ── Load fact table ──
fact = load_fact_table(MODELED_DIR)
"""),
        code("""
# ── Compute taste drift ──
drift_results = compute_taste_drift(fact)

# Display centroids
centroids = drift_results["centroids"]
feature_cols_display = [c for c in DRIFT_FEATURE_COLS if c in centroids.columns]
print("\\n📊 Temporal Centroids:")
print(centroids[["time_range"] + feature_cols_display].to_string(index=False, float_format="{:.4f}".format))
"""),
        md("""
### 4.2 — Drift Score & Interpretation
"""),
        code("""
# ── Display drift metrics ──
print("=" * 50)
print(f"  🎯 TASTE DRIFT SCORE: {drift_results['drift_score']:.4f}")
print(f"  📝 {drift_results['drift_label']}")
print(f"  🔒 Stability Score:  {drift_results['stability_score']:.4f}")
print("=" * 50)

print("\\n📐 Pairwise Cosine Distances:")
for pair, dist in drift_results["pairwise_distances"].items():
    bar = "█" * int(dist * 100) + "░" * (20 - int(dist * 100))
    print(f"  {pair:30s} {dist:.4f}  {bar}")
"""),
        md("""
### 4.3 — Feature Deltas: What's Driving the Drift?

Per-feature comparison between short-term and long-term centroids.
"""),
        code("""
# ── Feature deltas ──
deltas = drift_results["feature_deltas"]
if not deltas.empty:
    print("\\n📊 Feature Changes (short_term vs long_term):\\n")
    display_deltas = deltas[["label", "short_term", "long_term", "relative_delta_pct", "direction"]].copy()
    display_deltas.columns = ["Feature", "Short Term", "Long Term", "Δ (%)", "Direction"]
    print(display_deltas.to_string(index=False))
"""),
    ]


def section_visualizations():
    return [
        md("""
---
## Section 5: Visualizations

Five publication-quality visualizations demonstrating taste evolution.
"""),
        md("### 5.1 — Drift Radar: Acoustic Profiles Overlaid"),
        code("""
fig = plot_drift_radar(drift_results["centroids"])
plt.show()
"""),
        md("""
**Reading the radar:** Where the polygons diverge, taste is shifting.
Where they overlap, taste is stable. The green (short-term) polygon
pulling away from pink (long-term) indicates active drift in that feature.
"""),
        md("### 5.2 — Temporal Heatmap: Feature Intensity × Time Range"),
        code("""
fig = plot_temporal_heatmap(drift_results["centroids"])
plt.show()
"""),
        md("""
**Reading the heatmap:** Hot (bright) cells indicate high values; cool (dark)
cells indicate low values. Compare columns across rows to see which features
change most across time ranges.
"""),
        md("### 5.3 — UMAP Taste Map: Do Clusters Shift?"),
        code("""
fig = plot_umap_by_time_range(fact)
plt.show()
"""),
        md("""
**Reading the taste map:** Each dot is a track, colored by time range.
If short-term tracks (green) cluster separately from long-term (pink),
the user's taste has genuinely shifted — not just a few outlier tracks.
"""),
        md("### 5.4 — Artist Distribution: Temporal Flow"),
        code("""
fig = plot_genre_flow(fact)
plt.show()
"""),
        md("### 5.5 — Feature Distributions: Box Plots by Time Range"),
        code("""
fig = plot_feature_distributions(fact)
plt.show()
"""),
        md("""
**Reading the box plots:** The boxes show the interquartile range (25th–75th percentile).
If the entire box shifts between time ranges (not just outliers), the drift is a
genuine distributional shift, not driven by a few extreme tracks.
"""),
    ]


def section_warehouse_queries():
    return [
        md("""
---
## Section 6: Agent-Ready Insight Queries

These queries demonstrate the star schema's value for AI agent consumption.
Each query returns a deterministic, structured answer.
"""),
        code("""
# Query 1: What is the user's highest-energy track per time range?
print("🔍 Query 1: Highest-Energy Track Per Time Range\\n")
if "rms_mean" in fact.columns:
    for tr in ["short_term", "medium_term", "long_term"]:
        subset = fact[fact["time_range"] == tr]
        if not subset.empty and "rms_mean" in subset.columns:
            top = subset.nlargest(1, "rms_mean").iloc[0]
            print(f"  {tr:15s} → {top.get('track_name', 'N/A'):35s} (energy: {top['rms_mean']:.4f})")
"""),
        code("""
# Query 2: How many unique tracks appear in multiple time ranges?
print("🔍 Query 2: Track Persistence Across Time Ranges\\n")
track_ranges = fact.groupby("spotify_track_id")["time_range"].nunique()
multi = track_ranges[track_ranges > 1]
print(f"  Tracks appearing in 1 time range:  {(track_ranges == 1).sum()}")
print(f"  Tracks appearing in 2+ time ranges: {len(multi)}")
if len(multi) > 0:
    print(f"\\n  Persistent tracks (appear across time ranges):")
    for tid in multi.index[:5]:
        name = fact[fact["spotify_track_id"] == tid]["track_name"].iloc[0]
        ranges = fact[fact["spotify_track_id"] == tid]["time_range"].unique()
        print(f"    {name:35s} → {', '.join(ranges)}")
"""),
        code("""
# Query 3: Average acoustic profile per time range (agent-friendly)
print("🔍 Query 3: Acoustic Summary Per Time Range\\n")
summary_features = ["tempo_bpm", "rms_mean", "harmonic_ratio", "spectral_centroid_mean"]
available_sf = [c for c in summary_features if c in fact.columns]
if available_sf:
    summary = fact.groupby("time_range")[available_sf].mean()
    for col in available_sf:
        desc = COLUMN_DESCRIPTIONS.get(col, col)
        print(f"  {col}: {desc[:60]}")
    print()
    print(summary.round(4).to_string())
"""),
        code("""
# Query 4: Feature with the largest temporal shift
print("\\n🔍 Query 4: Biggest Taste Shift Driver\\n")
deltas = drift_results["feature_deltas"]
if not deltas.empty:
    top_delta = deltas.iloc[0]
    arrow = "↑" if top_delta["direction"] == "increasing" else "↓"
    print(f"  {arrow} {top_delta['label']}: {top_delta['relative_delta_pct']:.1f}% change")
    print(f"    Short-term value: {top_delta['short_term']:.4f}")
    print(f"    Long-term value:  {top_delta['long_term']:.4f}")
    print(f"    Direction:        {top_delta['direction']}")
"""),
    ]


def section_closing():
    return [
        md("""
---
## Section 7: Pipeline Summary & Architecture

### Data Lineage

```
Spotify API (3 time ranges, 50 tracks each)
    │
    ▼
STAGING (data/staging/)
    │  tracks_raw_*.parquet + features_raw_*.parquet
    │  + lineage: _landed_at, _source, _snapshot_label
    │
    ▼
CLEANSED (data/cleansed/)
    │  Dedup: (track_id, time_range) for tracks; track_id for features
    │  Type enforcement: Float32 features, String IDs, Bool flags
    │  Null handling: numerics → 0.0, strings → "unknown"
    │
    ▼
MODELED (data/modeled/)
    │  fact_listening_features: grain = track × time_range
    │  dim_tracks, dim_artists, dim_time_range
    │  column_descriptions (28 agent-readable descriptions)
    │
    ▼
ANALYSIS
    Taste Drift Score, Temporal Centroids, Feature Deltas
    5 publication-quality visualizations
```

### Tech Stack

| Component | Technology | Why |
|---|---|---|
| Audio DSP | librosa + numpy | Industry-standard MIR, 77D feature vectors |
| Batch Processing | PySpark | Distributed transforms, cluster-ready |
| Serialization | Apache Parquet (PyArrow) | Columnar, typed, compressed |
| Vector Search | FAISS | 10M vectors/sec cosine similarity |
| Dimensionality Reduction | UMAP | Preserves local + global structure |
| Visualization | matplotlib | Full control, dark theme consistency |

### PySpark Jobs (Cluster-Ready)

The warehouse transforms exist in both pandas (`src/warehouse/`) and PySpark (`spark/`) versions:

```bash
# Run distributed transforms
spark-submit spark/feature_transform.py    # Staging → Cleansed
spark-submit spark/temporal_aggregate.py   # Centroids + drift metrics
```

---
*Temporal Audio Pipeline — Jordan Vercillo, 2026*
*Built for the love of music data.*
"""),
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ASSEMBLY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build():
    nb = new_notebook()
    nb.metadata.kernelspec = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }

    sections = [
        ("Header", section_header),
        ("Setup", section_setup),
        ("Data Generation", section_data_generation),
        ("Medallion Pipeline", section_medallion),
        ("Drift Analysis", section_drift_analysis),
        ("Visualizations", section_visualizations),
        ("Warehouse Queries", section_warehouse_queries),
        ("Closing", section_closing),
    ]

    for name, builder in sections:
        print(f"   Adding section: {name}")
        nb.cells.extend(builder())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        nbf.write(nb, f)

    print(f"\n[OK] Notebook written: {OUTPUT_PATH}")
    print(f"   Cells: {len(nb.cells)}")


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    build()
