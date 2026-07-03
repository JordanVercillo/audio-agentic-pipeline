"""
faiss_store.py — FAISS Vector Index for Audio Similarity Search
================================================================
Manages a FAISS (Facebook AI Similarity Search) index for finding
acoustically similar tracks using cosine similarity.

Why FAISS over brute-force numpy?
    - FAISS uses optimized BLAS routines and SIMD instructions for
      vector comparison, making it 10-100x faster than raw numpy
      on large collections (>1K vectors).
    - Supports approximate nearest neighbor (ANN) algorithms like
      IVF and HNSW for sub-linear search on massive datasets.
    - For our use case (<100K tracks), exact search (IndexFlatIP)
      is fast enough and guarantees perfect recall.

Why IndexFlatIP with L2-normalized vectors?
    FAISS doesn't have a native "cosine similarity" index. However,
    inner product on L2-normalized vectors IS cosine similarity:
        cos(a, b) = a·b / (||a|| * ||b||)
    When ||a|| = ||b|| = 1 (L2-normalized), this simplifies to:
        cos(a, b) = a·b = inner_product(a, b)
    So we normalize all vectors before insertion and use IndexFlatIP.

Reference: 03_data_orchestrator.md — "Use Cosine Similarity to query"
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

try:
    import faiss
except ImportError:
    raise ImportError(
        "FAISS is required for vector search.\n"
        "Install: pip install faiss-cpu"
    )

from .config import VectorStoreConfig, VECTOR_STORE_DIR


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FAISS VECTOR STORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FAISSStore:
    """
    Manages a FAISS index for audio embedding similarity search.

    Usage:
        >>> store = FAISSStore(dimension=77)
        >>> store.add(vectors, track_ids)
        >>> results = store.query(query_vector, k=10)
        >>> store.save()
        >>> store = FAISSStore.load("path/to/faiss.index")
    """

    def __init__(
        self,
        dimension: int,
        config: Optional[VectorStoreConfig] = None,
    ):
        """
        Initialize a new FAISS store.

        Args:
            dimension: Embedding dimensionality (77 for DSP summary, 2048 for PANNs).
            config:    Optional VectorStoreConfig override.
        """
        self.config = config or VectorStoreConfig()
        self.dimension = dimension

        # IndexFlatIP = exact inner product search.
        # Combined with L2-normalized vectors, this gives us cosine similarity.
        self.index = faiss.IndexFlatIP(dimension)

        # Metadata: maps FAISS internal index position → spotify_track_id + info
        self._track_ids: list[str] = []
        self._metadata: list[dict] = []

    @property
    def size(self) -> int:
        """Number of vectors in the index."""
        return self.index.ntotal

    def add(
        self,
        vectors: np.ndarray,
        track_ids: list[str],
        metadata: Optional[list[dict]] = None,
    ) -> int:
        """
        Add vectors to the FAISS index.

        Vectors are L2-normalized before insertion so that inner product
        search produces cosine similarity scores.

        Args:
            vectors:   Shape (n, dimension), float32.
            track_ids: Spotify track IDs, positionally aligned with vectors.
            metadata:  Optional list of metadata dicts per vector.

        Returns:
            New total count of vectors in the index.

        Raises:
            ValueError: If shapes don't match or dimension is wrong.
        """
        vectors = np.asarray(vectors, dtype=np.float32)

        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        # FAISS requires C-contiguous arrays for SIMD operations.
        # Pandas .values on column subsets can return non-contiguous views.
        if not vectors.flags['C_CONTIGUOUS']:
            vectors = np.ascontiguousarray(vectors)

        if vectors.shape[1] != self.dimension:
            raise ValueError(
                f"Vector dimension mismatch: expected {self.dimension}, "
                f"got {vectors.shape[1]}"
            )

        if len(track_ids) != vectors.shape[0]:
            raise ValueError(
                f"track_ids length ({len(track_ids)}) must match "
                f"vectors count ({vectors.shape[0]})"
            )

        # L2-normalize: ensures inner product = cosine similarity
        faiss.normalize_L2(vectors)

        self.index.add(vectors)
        self._track_ids.extend(track_ids)

        if metadata:
            self._metadata.extend(metadata)
        else:
            self._metadata.extend([{}] * vectors.shape[0])

        return self.size

    def query(
        self,
        query_vector: np.ndarray,
        k: Optional[int] = None,
        exclude_self: bool = True,
    ) -> list[dict]:
        """
        Find the k most similar tracks to a query vector.

        Args:
            query_vector: Shape (dimension,) or (1, dimension), float32.
            k:            Number of results (default: config.n_results).
            exclude_self: If True, skip exact matches (distance ≈ 1.0).

        Returns:
            List of dicts sorted by similarity (highest first):
            [
                {
                    "spotify_track_id": "...",
                    "similarity": 0.95,    # cosine similarity [0, 1]
                    "rank": 1,
                    **metadata
                },
                ...
            ]
        """
        if self.size == 0:
            return []

        k = k or self.config.n_results
        # Request extra results in case we need to filter out self-match
        k_search = min(k + 1, self.size)

        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)

        # Normalize query vector for cosine similarity
        faiss.normalize_L2(query)

        # Search: returns (distances, indices) arrays of shape (1, k_search)
        distances, indices = self.index.search(query, k_search)

        results = []
        rank = 1
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue  # FAISS returns -1 for empty slots

            # Inner product on normalized vectors = cosine similarity ∈ [-1, 1]
            similarity = float(dist)

            # Skip exact self-match (cosine ≈ 1.0)
            if exclude_self and similarity > 0.9999:
                continue

            result = {
                "spotify_track_id": self._track_ids[idx],
                "similarity": similarity,
                "rank": rank,
            }
            if self._metadata[idx]:
                result.update(self._metadata[idx])

            results.append(result)
            rank += 1

            if len(results) >= k:
                break

        return results

    def query_by_track_id(
        self,
        track_id: str,
        k: Optional[int] = None,
    ) -> list[dict]:
        """
        Find tracks similar to an existing track in the index.

        Looks up the track's vector by its spotify_track_id, then
        performs a similarity search excluding the query track itself.

        Args:
            track_id: Spotify track ID of the query track.
            k:        Number of results.

        Returns:
            List of similar track dicts (same format as query()).

        Raises:
            KeyError: If track_id is not in the index.
        """
        try:
            idx = self._track_ids.index(track_id)
        except ValueError:
            raise KeyError(f"Track '{track_id}' not found in index")

        # Reconstruct the vector from the index
        vector = self.index.reconstruct(idx)
        return self.query(vector, k=k, exclude_self=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  PERSISTENCE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def save(
        self,
        index_path: Optional[Union[str, Path]] = None,
        metadata_path: Optional[Union[str, Path]] = None,
    ) -> tuple[Path, Path]:
        """
        Persist the FAISS index and metadata to disk.

        FAISS index is saved as a binary file.
        Metadata (track_ids + extra) is saved as Parquet for type safety.
        """
        idx_path = Path(index_path or self.config.index_path).resolve()
        meta_path = Path(metadata_path or self.config.metadata_path).resolve()

        idx_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self.index, str(idx_path))

        # Save metadata as Parquet
        meta_df = pd.DataFrame({
            "position": range(len(self._track_ids)),
            "spotify_track_id": self._track_ids,
        })
        # Merge extra metadata if present
        if self._metadata and any(m for m in self._metadata):
            extra = pd.DataFrame(self._metadata)
            meta_df = pd.concat([meta_df, extra], axis=1)

        meta_df.to_parquet(meta_path, engine="pyarrow", index=False)

        print(f"   💾 Saved FAISS index: {self.size} vectors → {idx_path.name}")
        print(f"   💾 Saved metadata: {len(meta_df)} rows → {meta_path.name}")

        return idx_path, meta_path

    @classmethod
    def load(
        cls,
        index_path: Optional[Union[str, Path]] = None,
        metadata_path: Optional[Union[str, Path]] = None,
        config: Optional[VectorStoreConfig] = None,
    ) -> "FAISSStore":
        """
        Load a persisted FAISS index and metadata from disk.

        Returns a fully populated FAISSStore ready for queries.
        """
        cfg = config or VectorStoreConfig()
        idx_path = Path(index_path or cfg.index_path).resolve()
        meta_path = Path(metadata_path or cfg.metadata_path).resolve()

        if not idx_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {idx_path}")
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {meta_path}")

        # Load FAISS index
        index = faiss.read_index(str(idx_path))
        dimension = index.d

        # Load metadata
        meta_df = pd.read_parquet(meta_path, engine="pyarrow")

        # Reconstruct store
        store = cls(dimension=dimension, config=cfg)
        store.index = index
        store._track_ids = meta_df["spotify_track_id"].tolist()

        # Rebuild metadata dicts from extra columns
        extra_cols = [c for c in meta_df.columns if c not in ("position", "spotify_track_id")]
        if extra_cols:
            store._metadata = meta_df[extra_cols].to_dict("records")
        else:
            store._metadata = [{}] * len(store._track_ids)

        print(f"   📂 Loaded FAISS index: {store.size} vectors ({dimension}D)")
        return store

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  UTILITIES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def get_all_vectors(self) -> np.ndarray:
        """
        Reconstruct all vectors from the index.
        Returns shape (n_vectors, dimension).
        """
        if self.size == 0:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.array(
            [self.index.reconstruct(i) for i in range(self.size)],
            dtype=np.float32,
        )

    def get_all_track_ids(self) -> list[str]:
        """Return all spotify_track_ids in insertion order."""
        return list(self._track_ids)

    def __repr__(self) -> str:
        return (
            f"FAISSStore(dimension={self.dimension}, size={self.size}, "
            f"metric=cosine)"
        )
