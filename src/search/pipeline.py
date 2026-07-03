"""
pipeline.py — End-to-End DAG Orchestrator
==========================================
Implements the 3-step DAG from 03_data_orchestrator.md:

    Step 1: Fetch Metadata (API)
         ↓
    Step 2: Extract Features (DSP)
         ↓
    Step 3: Upsert to Vector Store

Each step is independently callable, but this module provides
convenience functions that chain them together.
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from .config import VectorStoreConfig
from .faiss_store import FAISSStore
from .visualizer import compute_umap, plot_taste_map


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 3: BUILD VECTOR INDEX FROM FEATURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_index_from_features(
    features_parquet: Union[str, Path],
    config: Optional[VectorStoreConfig] = None,
    save: bool = True,
) -> FAISSStore:
    """
    Build a FAISS index from a DSP features Parquet file.

    Reads the summary features, computes a summary vector per track
    (by collecting all numeric columns), and upserts into FAISS.

    This is the "Step 3" of the DAG: features → vector store.

    Args:
        features_parquet: Path to DSP features Parquet file (from src.dsp.serializer).
        config:           Optional VectorStoreConfig.
        save:             If True, persist the index to disk after building.

    Returns:
        A populated FAISSStore ready for similarity queries.
    """
    config = config or VectorStoreConfig()

    df = pd.read_parquet(features_parquet, engine="pyarrow")
    print(f"   📂 Loaded {len(df)} tracks from {Path(features_parquet).name}")

    if "spotify_track_id" not in df.columns:
        raise ValueError("Features Parquet must contain 'spotify_track_id' column")

    track_ids = df["spotify_track_id"].tolist()

    # Extract numeric feature columns for the embedding vector
    exclude_cols = {
        "spotify_track_id", "file_name", "file_path",
        "estimated_key", "estimated_mode", "beat_count",
    }
    numeric_cols = [
        c for c in df.select_dtypes(include=[np.number]).columns
        if c not in exclude_cols
    ]
    vectors = df[numeric_cols].fillna(0).values.astype(np.float32)

    print(f"   🔢 Feature vector: {vectors.shape[1]}D from {len(numeric_cols)} columns")

    # Build metadata dicts for each track (non-numeric columns)
    meta_cols = ["file_name", "estimated_mode"]
    meta_cols = [c for c in meta_cols if c in df.columns]
    metadata = df[meta_cols].to_dict("records") if meta_cols else None

    # Create and populate the FAISS index
    store = FAISSStore(dimension=vectors.shape[1], config=config)
    store.add(vectors, track_ids, metadata=metadata)

    print(f"   ✅ Built FAISS index: {store.size} vectors ({store.dimension}D)")

    if save:
        store.save()

    return store


def build_index_from_embeddings(
    embeddings_parquet: Union[str, Path],
    config: Optional[VectorStoreConfig] = None,
    save: bool = True,
) -> FAISSStore:
    """
    Build a FAISS index from an embeddings Parquet file (PANNs or summary).

    Unlike build_index_from_features (which uses raw DSP columns),
    this uses pre-computed dense embedding vectors (77D or 2048D).

    Args:
        embeddings_parquet: Path to embeddings Parquet (from src.dsp.serializer).
        config:             Optional VectorStoreConfig.
        save:               If True, persist the index after building.

    Returns:
        A populated FAISSStore.
    """
    config = config or VectorStoreConfig()

    from src.dsp.serializer import load_embeddings_as_matrix
    vectors, track_ids = load_embeddings_as_matrix(embeddings_parquet)

    print(f"   🔢 Embedding vector: {vectors.shape[1]}D")

    store = FAISSStore(dimension=vectors.shape[1], config=config)
    store.add(vectors, track_ids)

    print(f"   ✅ Built FAISS index: {store.size} vectors ({store.dimension}D)")

    if save:
        store.save()

    return store


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIMILARITY SEARCH (HIGH-LEVEL)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_similar_tracks(
    track_id: str,
    store: Optional[FAISSStore] = None,
    k: int = 10,
    config: Optional[VectorStoreConfig] = None,
) -> pd.DataFrame:
    """
    Find the k most similar tracks to a given track.

    If no store is provided, attempts to load the default persisted index.

    Args:
        track_id: Spotify track ID of the query track.
        store:    Pre-loaded FAISSStore. If None, loads from default path.
        k:        Number of similar tracks to return.
        config:   Optional VectorStoreConfig.

    Returns:
        DataFrame with columns: spotify_track_id, similarity, rank, + metadata.
    """
    if store is None:
        store = FAISSStore.load(config=config)

    results = store.query_by_track_id(track_id, k=k)

    if not results:
        print(f"   ⚠️  No similar tracks found for {track_id}")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    print(f"   🎯 Top {len(df)} similar tracks to {track_id}:")
    for _, row in df.head(5).iterrows():
        sim_pct = row["similarity"] * 100
        print(f"      {row['rank']}. {row['spotify_track_id']} — {sim_pct:.1f}% similar")

    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VISUALIZATION (HIGH-LEVEL)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def visualize_collection(
    store: Optional[FAISSStore] = None,
    labels: Optional[list[str]] = None,
    colors: Optional[list[str]] = None,
    color_label: str = "Genre",
    title: str = "Musical Taste Map (UMAP)",
    config: Optional[VectorStoreConfig] = None,
    save_path: Optional[Union[str, Path]] = None,
):
    """
    Generate a UMAP taste map from the vector index.

    Extracts all vectors from the FAISS store, projects them to 2D
    via UMAP, and renders a publication-quality scatter plot.

    Args:
        store:       FAISSStore to visualize. Loads default if None.
        labels:      Track labels (names). If None, uses track IDs.
        colors:      Category per track (e.g., genre, artist). If None, uniform color.
        color_label: Legend title.
        title:       Plot title.
        config:      UMAP/store config.
        save_path:   Optional path to save the figure.

    Returns:
        (projection, figure): The 2D UMAP coordinates and matplotlib Figure.
    """
    config = config or VectorStoreConfig()

    if store is None:
        store = FAISSStore.load(config=config)

    vectors = store.get_all_vectors()
    track_ids = store.get_all_track_ids()

    if labels is None:
        labels = track_ids

    print(f"   🗺️  Computing UMAP projection for {len(vectors)} tracks...")
    projection = compute_umap(vectors, config=config)

    fig = plot_taste_map(
        projection,
        labels=labels,
        colors=colors,
        color_label=color_label,
        title=title,
        save_path=save_path,
    )

    return projection, fig
