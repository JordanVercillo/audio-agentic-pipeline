"""
config.py — UMAP projection configuration
=========================================
Configuration for the taste-map projection.

This file used to carry the FAISS vector-store settings too (`metric`,
`index_path`, `SimilarityMetric`). Those went with the FAISS stack on
2026-07-31 - see `docs/DELETIONS.md`. Similarity is answered today by a plain
`math.dist` scan in `src/store/cache.py`.

Key design decision:
    - UMAP for dimensionality reduction (NOT PCA or t-SNE).
      Why? UMAP preserves both local AND global topological structure.
      PCA only captures linear variance. t-SNE preserves local structure
      but distorts global relationships (clusters appear equally spaced
      regardless of actual similarity). UMAP is the industry standard
      for visualizing music genre clusters.
"""

from dataclasses import dataclass, field
from pathlib import Path

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATHS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VECTOR STORE CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class VectorStoreConfig:
    """
    Runtime configuration for the vector similarity search engine.

    Attributes:
        metadata_path:  Path to the Parquet file mapping projection rows
                        to spotify_track_ids and other metadata.
        n_results:      Default number of results for similarity queries.
        umap_n_neighbors:   UMAP locality parameter. Higher = more global
                            structure preserved (default: 15).
        umap_min_dist:      UMAP minimum distance between embedded points.
                            Lower = tighter clusters (default: 0.1).
        umap_n_components:  Output dimensionality for UMAP (2 for 2D viz,
                            3 for 3D viz).
        umap_random_state:  Seed - keeps the committed taste map reproducible.
                            Unseeded, every rebuild would redraw it and no
                            diff would ever mean anything.
    """
    metadata_path: Path = field(default_factory=lambda: VECTOR_STORE_DIR / "index_metadata.parquet")
    n_results: int = 10

    # UMAP parameters
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    umap_n_components: int = 2
    umap_random_state: int = 42
