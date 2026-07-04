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

import importlib

# Configuration
from .config import VectorStoreConfig, SimilarityMetric

# Visualization (light: umap + matplotlib — needed by the taste-map path)
from .visualizer import compute_umap, plot_taste_map, plot_similarity_radar

# ── Lazy heavy submodules ──
# FAISS (faiss_store) and the full DAG (pipeline) are loaded ON FIRST ACCESS,
# not at package import. Otherwise `from src.search.visualizer import compute_umap`
# — the taste-map / report path — would drag in FAISS it never uses (and emit
# faiss's AVX-fallback noise). `from src.search import FAISSStore` still works.
_LAZY = {
    "FAISSStore": ".faiss_store",
    "build_index_from_features": ".pipeline",
    "build_index_from_embeddings": ".pipeline",
    "find_similar_tracks": ".pipeline",
    "visualize_collection": ".pipeline",
}


def __getattr__(name: str):  # PEP 562
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target, __name__), name)


def __dir__():
    return sorted([*globals().keys(), *_LAZY])


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
