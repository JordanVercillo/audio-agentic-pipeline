"""
config.py — Vector Search Configuration
=========================================
Centralized configuration for the vector similarity search layer.

Key design decisions (per 03_data_orchestrator.md):
    - Cosine similarity (NOT Euclidean) for all vector comparisons.
      Why? Audio embeddings live on a manifold where direction matters
      more than magnitude. Two quiet recordings of the same song should
      match despite having different absolute energy levels. Cosine
      similarity measures angular distance, making it magnitude-invariant.

    - UMAP for dimensionality reduction (NOT PCA or t-SNE).
      Why? UMAP preserves both local AND global topological structure.
      PCA only captures linear variance. t-SNE preserves local structure
      but distorts global relationships (clusters appear equally spaced
      regardless of actual similarity). UMAP is the industry standard
      for visualizing music genre clusters.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATHS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIMILARITY METRICS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SimilarityMetric(Enum):
    """
    Supported similarity/distance metrics for vector search.

    COSINE is the default and ONLY recommended metric per
    03_data_orchestrator.md. Others are available for experimentation
    but should not be used on raw audio embeddings.
    """
    COSINE = "cosine"          # Angular distance — magnitude-invariant (RECOMMENDED)
    INNER_PRODUCT = "ip"       # Dot product — requires normalized vectors
    L2 = "l2"                  # Euclidean — NOT recommended for audio embeddings


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VECTOR STORE CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class VectorStoreConfig:
    """
    Runtime configuration for the vector similarity search engine.

    Attributes:
        metric:         Similarity metric (default: COSINE).
        index_path:     Path to persist the FAISS index file.
        metadata_path:  Path to the Parquet file mapping index positions
                        to spotify_track_ids and other metadata.
        n_results:      Default number of results for similarity queries.
        umap_n_neighbors:   UMAP locality parameter. Higher = more global
                            structure preserved (default: 15).
        umap_min_dist:      UMAP minimum distance between embedded points.
                            Lower = tighter clusters (default: 0.1).
        umap_n_components:  Output dimensionality for UMAP (2 for 2D viz,
                            3 for 3D viz).
    """
    metric: SimilarityMetric = SimilarityMetric.COSINE
    index_path: Path = field(default_factory=lambda: VECTOR_STORE_DIR / "faiss.index")
    metadata_path: Path = field(default_factory=lambda: VECTOR_STORE_DIR / "index_metadata.parquet")
    n_results: int = 10

    # UMAP parameters
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    umap_n_components: int = 2
    umap_random_state: int = 42
