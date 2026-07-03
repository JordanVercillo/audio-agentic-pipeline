"""
serializer.py — Parquet Serialization with Spotify Bridge Key
=============================================================
Handles all persistence of DSP outputs. Enforces the data contract
from 03_data_orchestrator.md:

    1. NEVER store feature matrices in CSV — always Parquet/Arrow.
    2. Every row MUST contain a spotify_track_id bridging key.
    3. Use strict Float32 typing for all numeric DSP columns.
    4. Support incremental appends (new tracks added to existing file).

Why Parquet over CSV?
    - Preserves strict data types (Float32 vs Float64) — no silent casting.
    - Columnar compression: 5-10x smaller than CSV for dense numeric data.
    - Supports nested array columns (for storing variable-length embeddings).
    - Native PyArrow/pandas integration for zero-copy reads.

Reference: 03_data_orchestrator.md — "Data Storage Protocols"
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    raise ImportError(
        "PyArrow is required for Parquet serialization.\n"
        "Install: pip install pyarrow>=14.0.0"
    )

from .feature_extractor import TrackFeatures
from .embedding_extractor import AudioEmbedding


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEATURE SUMMARY → PARQUET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_features_to_parquet(
    features_list: list[TrackFeatures],
    output_path: Union[str, Path],
    spotify_track_ids: Optional[list[str]] = None,
    append: bool = True,
) -> Path:
    """
    Serialize a list of TrackFeatures to Parquet.

    Each TrackFeatures is flattened into a single row via .to_summary_dict(),
    then enriched with the mandatory spotify_track_id bridge column.

    Args:
        features_list:     List of TrackFeatures from feature_extractor.
        output_path:       Path to .parquet file.
        spotify_track_ids: List of Spotify track IDs, positionally aligned
                           with features_list. If None, placeholder IDs
                           are generated (must be filled before joining
                           with ingestion layer).
        append:            If True and file exists, append new rows.
                           If False, overwrite.

    Returns:
        Path to the written Parquet file.

    Raises:
        ValueError: If spotify_track_ids length doesn't match features_list.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build records
    records = []
    for i, feat in enumerate(features_list):
        row = feat.to_summary_dict()

        # ── Enforce the bridging key ──
        if spotify_track_ids is not None:
            if len(spotify_track_ids) != len(features_list):
                raise ValueError(
                    f"spotify_track_ids length ({len(spotify_track_ids)}) "
                    f"must match features_list length ({len(features_list)})"
                )
            row["spotify_track_id"] = spotify_track_ids[i]
        else:
            # Placeholder — user must fill this before joining with API metadata
            row["spotify_track_id"] = f"PENDING_{feat.file_name}"

        records.append(row)

    df_new = pd.DataFrame(records)

    # Cast numeric columns to Float32 for storage efficiency and type safety
    float_cols = df_new.select_dtypes(include=[np.floating, np.integer]).columns
    for col in float_cols:
        if col not in ("beat_count", "estimated_key"):  # keep these as int
            df_new[col] = df_new[col].astype(np.float32)

    # ── Append or overwrite ──
    if append and output_path.exists():
        df_existing = pd.read_parquet(output_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        # Deduplicate by spotify_track_id (keep latest)
        df_combined = df_combined.drop_duplicates(
            subset=["spotify_track_id"], keep="last"
        )
        df_combined.to_parquet(output_path, engine="pyarrow", index=False)
        print(f"   📝 Appended {len(df_new)} rows → {output_path.name} "
              f"(total: {len(df_combined)})")
    else:
        df_new.to_parquet(output_path, engine="pyarrow", index=False)
        print(f"   💾 Saved {len(df_new)} rows → {output_path.name}")

    return output_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EMBEDDINGS → PARQUET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_embeddings_to_parquet(
    embeddings: list[AudioEmbedding],
    output_path: Union[str, Path],
    spotify_track_ids: Optional[list[str]] = None,
    append: bool = True,
) -> Path:
    """
    Serialize embeddings to Parquet with the spotify_track_id bridge.

    Each embedding vector is stored as a list column (PyArrow list_ type),
    preserving the full dimensionality in a single cell. This is more
    storage-efficient than exploding 2048 dimensions into 2048 columns.

    Args:
        embeddings:        List of AudioEmbedding objects.
        output_path:       Path to .parquet file.
        spotify_track_ids: Spotify track IDs aligned with embeddings.
        append:            If True and file exists, append.

    Returns:
        Path to the written Parquet file.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for i, emb in enumerate(embeddings):
        row = {
            "file_name": emb.file_name,
            "file_path": emb.file_path,
            "duration_sec": np.float32(emb.duration_sec),
            "model_name": emb.model_name,
            "embedding_dim": emb.embedding_dim,
            # Store the full vector as a Python list (PyArrow handles list_ type)
            "embedding": emb.embedding.tolist(),
        }

        if spotify_track_ids is not None:
            if len(spotify_track_ids) != len(embeddings):
                raise ValueError(
                    f"spotify_track_ids length ({len(spotify_track_ids)}) "
                    f"must match embeddings length ({len(embeddings)})"
                )
            row["spotify_track_id"] = spotify_track_ids[i]
        else:
            row["spotify_track_id"] = f"PENDING_{emb.file_name}"

        records.append(row)

    df_new = pd.DataFrame(records)

    if append and output_path.exists():
        df_existing = pd.read_parquet(output_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(
            subset=["spotify_track_id"], keep="last"
        )
        df_combined.to_parquet(output_path, engine="pyarrow", index=False)
        print(f"   📝 Appended {len(df_new)} embeddings → {output_path.name} "
              f"(total: {len(df_combined)})")
    else:
        df_new.to_parquet(output_path, engine="pyarrow", index=False)
        print(f"   💾 Saved {len(df_new)} embeddings → {output_path.name}")

    return output_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  READ-BACK UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_features_parquet(path: Union[str, Path]) -> pd.DataFrame:
    """Load a features Parquet file back into a DataFrame."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")
    df = pd.read_parquet(path, engine="pyarrow")
    print(f"   📂 Loaded {len(df)} rows from {path.name}")
    return df


def load_embeddings_as_matrix(
    path: Union[str, Path],
) -> tuple[np.ndarray, list[str]]:
    """
    Load embeddings Parquet and return as a numpy matrix + track IDs.

    This is the format needed for FAISS/ChromaDB vector upsert:
        matrix shape: (n_tracks, embedding_dim)
        ids: list of spotify_track_ids

    Returns:
        (embedding_matrix, spotify_track_ids)
    """
    df = load_features_parquet(path)

    # Convert list column back to numpy matrix
    vectors = np.array(df["embedding"].tolist(), dtype=np.float32)
    track_ids = df["spotify_track_id"].tolist()

    print(f"   🔢 Embedding matrix: {vectors.shape} ({vectors.dtype})")
    return vectors, track_ids
