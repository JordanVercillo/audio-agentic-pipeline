"""
src.search — Vector Similarity Search & Visualization
=======================================================
The final layer of the audio-agentic-pipeline. Indexes audio embeddings
in FAISS for sub-millisecond cosine similarity queries, and projects
collections into 2D taste maps via UMAP.

Architecture:
    config.py      → Vector store + UMAP configuration
    faiss_store.py → FAISS index management (add, query, persist)
    visualizer.py  → UMAP projection + dark-themed scatter/radar plots
    pipeline.py    → End-to-end DAG orchestrator

Quick Start:
    >>> from src.search import FAISSStore, find_similar_tracks

    # Build an index from DSP features
    >>> from src.search import build_index_from_features
    >>> store = build_index_from_features("data/embeddings/dsp_features.parquet")

    # Find similar tracks
    >>> results = find_similar_tracks("spotify:track:xxx", store=store, k=5)

    # Visualize the collection
    >>> from src.search import visualize_collection
    >>> projection, fig = visualize_collection(store=store)

Full DAG (from 03_data_orchestrator.md):
    1. Fetch Metadata (src.ingestion)
    2. Extract Features (src.dsp)
    3. Upsert to Vector Store (src.search)  ← this module
"""

# Configuration
from .config import VectorStoreConfig, SimilarityMetric

# FAISS Store
from .faiss_store import FAISSStore

# Visualization
from .visualizer import compute_umap, plot_taste_map, plot_similarity_radar

# Pipeline Orchestration
from .pipeline import (
    build_index_from_features,
    build_index_from_embeddings,
    find_similar_tracks,
    visualize_collection,
)

__all__ = [
    # Config
    "VectorStoreConfig", "SimilarityMetric",
    # FAISS
    "FAISSStore",
    # Visualization
    "compute_umap", "plot_taste_map", "plot_similarity_radar",
    # Pipeline
    "build_index_from_features", "build_index_from_embeddings",
    "find_similar_tracks", "visualize_collection",
]
