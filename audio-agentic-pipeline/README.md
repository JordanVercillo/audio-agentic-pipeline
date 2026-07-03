# 🎧 Temporal Audio Pipeline

**How Your Music Taste Evolves** — A data engineering portfolio project demonstrating
Medallion architecture, distributed processing, and temporal acoustic analysis.

---

## Architecture

```
Spotify API (3 time ranges)         Raw Audio Files
         │                                │
         ▼                                ▼
┌─────────────────┐              ┌─────────────────┐
│    STAGING       │              │    DSP Module     │
│  Raw API data    │              │  librosa → 77D    │
│  + lineage meta  │              │  feature vectors  │
└────────┬────────┘              └────────┬──────────┘
         │                                │
         ▼                                ▼
┌──────────────────────────────────────────────────┐
│                  CLEANSED                         │
│  Dedup · Type enforcement · Schema validation     │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│                   MODELED                         │
│  Star Schema (fact + dimensions)                  │
│  Agent-readable column descriptions               │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│               ANALYSIS                            │
│  Taste Drift Score · Centroids · Visualizations   │
└──────────────────────────────────────────────────┘
```

## Project Structure

```
audio-agentic-pipeline/
├── src/                          # Core Python modules
│   ├── ingestion/                #   Spotify API (PKCE auth, 2026-safe guardrails)
│   ├── dsp/                      #   Audio DSP (librosa → 77D feature vectors)
│   ├── warehouse/                #   Medallion transforms (staging/cleansed/modeled)
│   ├── analysis/                 #   Taste drift engine + visualizations
│   └── search/                   #   FAISS vector index + UMAP taste maps
├── spark/                        # PySpark batch jobs (cluster-ready)
│   ├── feature_transform.py      #   Staging → Cleansed distributed transform
│   └── temporal_aggregate.py     #   Centroid computation + drift metrics
├── notebooks/                    # Runnable deliverables
│   ├── temporal_analysis.ipynb   #   ★ Main deliverable: end-to-end taste drift
│   └── pipeline_walkthrough.ipynb#   DSP + Search module deep-dive
├── data/
│   ├── warehouse/                # Medallion data layers
│   │   ├── staging/              #   Raw Parquet (append-only, immutable)
│   │   ├── cleansed/             #   Deduped, typed, validated
│   │   └── modeled/              #   Star schema (fact + dimensions)
│   └── raw_audio/                # Audio files for DSP processing
├── requirements.txt
└── README.md
```

## Key Concepts

### Medallion Architecture
Three immutable data layers ensuring full auditability:
- **Staging** — Raw data exactly as received, with `_landed_at` and `_source` lineage
- **Cleansed** — Deduplicated by `(track_id, time_range)`, type-enforced, null-handled
- **Modeled** — Denormalized star schema with AI-agent-readable column descriptions

### Taste Drift Score
Cosine distance between short-term and long-term acoustic centroids:
- `0.00 – 0.05`: Minimal drift (comfort zone)
- `0.05 – 0.15`: Moderate drift (exploration)
- `0.15 – 0.30`: Significant drift (active evolution)
- `0.30+`: Major drift (genre shift)

### Bridge Key
`spotify_track_id` joins Spotify metadata with DSP features across all layers.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Generate the temporal analysis notebook (if needed)
python notebooks/build_temporal_analysis.py

# Run PySpark jobs (local mode)
spark-submit spark/feature_transform.py
spark-submit spark/temporal_aggregate.py
```

## Tech Stack

| Component | Technology |
|---|---|
| Audio DSP | librosa, numpy, soundfile |
| Data Serialization | Apache Parquet (PyArrow) |
| Batch Processing | PySpark 3.5+ |
| Vector Search | FAISS (cosine similarity) |
| Dimensionality Reduction | UMAP |
| Spotify API | spotipy (PKCE auth) |
| Visualization | matplotlib |

---

*Temporal Audio Pipeline — Jordan Vercillo, 2026*
