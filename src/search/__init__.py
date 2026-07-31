"""
src.search — UMAP projection for the taste map
==============================================
Projects the 77-dim acoustic fingerprints into 2D so a collection can be
plotted. `compute_umap` is consumed by `src.analysis.clustering` (the taste-map
path) and by `scripts/build_taste_map.py`.

Architecture:
    config.py     → UMAP configuration (seeded, so the map is reproducible)
    visualizer.py → UMAP projection + dark-themed scatter/radar plots

Quick Start:
    >>> from src.search import compute_umap
    >>> xy = compute_umap(vectors)          # (n, 2) float32, deterministic

This package used to own a FAISS vector-similarity index (`faiss_store.py`) and
an end-to-end DAG (`pipeline.py`). Both were deleted on 2026-07-31: nothing
imported them, and the live "similar tracks" answer is a plain `math.dist` scan
in `src/store/cache.py` at 7.7 ms over the corpus. See `docs/DELETIONS.md` for
what they did and the one command that restores them.
"""

# Configuration
from .config import VectorStoreConfig

# Visualization (umap + matplotlib — the taste-map path)
from .visualizer import compute_umap, plot_similarity_radar, plot_taste_map

__all__ = [
    "VectorStoreConfig",
    "compute_umap",
    "plot_taste_map",
    "plot_similarity_radar",
]
