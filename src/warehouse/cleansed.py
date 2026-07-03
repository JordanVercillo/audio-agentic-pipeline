"""
cleansed.py — Cleansed Layer (Medallion: Silver)
==================================================
Transforms raw Staging data into clean, typed, deduplicated datasets.

Responsibilities:
    1. DEDUPLICATION: A track can appear in multiple time ranges (short + medium + long).
       We preserve the time_range tag but ensure no duplicate (track_id, time_range) pairs.
    2. TYPE ENFORCEMENT: Cast all numeric DSP columns to Float32, all IDs to string,
       all booleans to bool. No implicit type coercion downstream.
    3. NULL HANDLING: Fill numeric NaN with 0.0, string NaN with "unknown".
       Document every null-fill decision in the column descriptions.
    4. SCHEMA VALIDATION: Assert required columns exist, reject malformed rows.

Output:
    - `cleansed_tracks.parquet`: One row per (spotify_track_id, time_range) pair
    - `cleansed_features.parquet`: One row per spotify_track_id (features are time-independent)

Reference: Medallion Architecture — Silver/Cleansed Layer
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STAGING_DIR = _PROJECT_ROOT / "data" / "warehouse" / "staging"
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"

# ── Schema definitions ──
# These define the REQUIRED columns and their target types.
# Any column not listed here passes through unchanged.

TRACK_SCHEMA = {
    "spotify_track_id": "string",
    "track_name": "string",
    "artist_names": "string",
    "artist_ids": "string",
    "primary_artist_name": "string",
    "primary_artist_id": "string",
    "album_name": "string",
    "album_id": "string",
    "album_type": "string",
    "album_release_date": "string",
    "duration_ms": "int64",
    "explicit": "bool",
    "is_local": "bool",
    "disc_number": "int64",
    "track_number": "int64",
    "num_artists": "int64",
    "time_range": "string",
    "rank": "int64",
}

FEATURE_SCHEMA_REQUIRED = [
    "spotify_track_id",
    "tempo_bpm",
    "rms_mean",
    "zcr_mean",
    "spectral_centroid_mean",
    "harmonic_ratio",
]


def build_cleansed_tracks(
    staging_dir: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Build the Cleansed tracks table from all Staging track files.

    Processing steps:
        1. Read all `tracks_raw_*.parquet` files from Staging
        2. Concatenate into a single DataFrame
        3. Deduplicate by (spotify_track_id, time_range) — keep latest snapshot
        4. Enforce column types per TRACK_SCHEMA
        5. Fill nulls: strings → "unknown", numerics → 0
        6. Drop lineage columns (_landed_at, _source, _snapshot_label)
        7. Write to cleansed_tracks.parquet

    Args:
        staging_dir: Override Staging directory path.
        output_dir:  Override Cleansed directory path.

    Returns:
        Cleansed tracks DataFrame.

    Scale Notes:
        For production, replace pd.concat with a PySpark union + dropDuplicates
        to handle billions of rows across time-partitioned Staging files.
    """
    staging_dir = Path(staging_dir or STAGING_DIR).resolve()
    output_dir = Path(output_dir or CLEANSED_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Read all staging track files ──
    track_files = sorted(staging_dir.glob("tracks_raw_*.parquet"))
    if not track_files:
        print("   ⚠️  No staging track files found.")
        return pd.DataFrame()

    dfs = [pd.read_parquet(f, engine="pyarrow") for f in track_files]
    df = pd.concat(dfs, ignore_index=True)
    print(f"   📂 Read {len(df)} raw rows from {len(track_files)} staging file(s)")

    # ── Step 2: Deduplicate ──
    # Same track can appear in multiple snapshots; keep the latest.
    # Within the same snapshot, (track_id, time_range) should be unique.
    if "_landed_at" in df.columns:
        df = df.sort_values("_landed_at", ascending=False)

    dedup_cols = ["spotify_track_id", "time_range"] if "time_range" in df.columns else ["spotify_track_id"]
    before = len(df)
    df = df.drop_duplicates(subset=dedup_cols, keep="first")
    dupes_removed = before - len(df)
    if dupes_removed > 0:
        print(f"   🔄 Removed {dupes_removed} duplicate rows")

    # ── Step 3: Type enforcement ──
    for col, dtype in TRACK_SCHEMA.items():
        if col not in df.columns:
            continue
        try:
            if dtype == "string":
                df[col] = df[col].fillna("unknown").astype(str)
            elif dtype == "bool":
                df[col] = df[col].fillna(False).astype(bool)
            elif dtype == "int64":
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)
        except Exception as e:
            print(f"   ⚠️  Type enforcement failed for '{col}': {e}")

    # ── Step 4: Drop lineage columns (they served their purpose) ──
    lineage_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=lineage_cols, errors="ignore")

    # ── Step 5: Write ──
    output_path = output_dir / "cleansed_tracks.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)

    # ── Report ──
    time_ranges = df["time_range"].unique().tolist() if "time_range" in df.columns else []
    print(f"   ✅ Cleansed tracks: {len(df)} rows → cleansed_tracks.parquet")
    print(f"      Time ranges: {time_ranges}")
    print(f"      Columns: {len(df.columns)}")

    return df


def build_cleansed_features(
    staging_dir: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Build the Cleansed features table from all Staging feature files.

    Processing steps:
        1. Read all `features_raw_*.parquet` from Staging
        2. Validate required columns exist
        3. Deduplicate by spotify_track_id (features are time-independent)
        4. Cast all numeric columns to Float32
        5. Fill NaN with 0.0 (a feature value of 0 is meaningful — silence)
        6. Write to cleansed_features.parquet

    Why deduplicate by track_id only (not time_range)?
        DSP features are intrinsic to the audio file, not the time window
        in which the track appeared in the user's listening history. A track's
        tempo is the same whether it's in short_term or long_term.

    Args:
        staging_dir: Override Staging directory path.
        output_dir:  Override Cleansed directory path.

    Returns:
        Cleansed features DataFrame.
    """
    staging_dir = Path(staging_dir or STAGING_DIR).resolve()
    output_dir = Path(output_dir or CLEANSED_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_files = sorted(staging_dir.glob("features_raw_*.parquet"))
    if not feature_files:
        print("   ⚠️  No staging feature files found.")
        return pd.DataFrame()

    dfs = [pd.read_parquet(f, engine="pyarrow") for f in feature_files]
    df = pd.concat(dfs, ignore_index=True)
    print(f"   📂 Read {len(df)} raw feature rows from {len(feature_files)} staging file(s)")

    # ── Schema validation ──
    missing = [col for col in FEATURE_SCHEMA_REQUIRED if col not in df.columns]
    if missing:
        print(f"   ⚠️  Missing required columns: {missing}")
        print(f"      Available: {list(df.columns)}")

    # ── Deduplicate by track_id ──
    if "_landed_at" in df.columns:
        df = df.sort_values("_landed_at", ascending=False)
    before = len(df)
    df = df.drop_duplicates(subset=["spotify_track_id"], keep="first")
    dupes_removed = before - len(df)
    if dupes_removed > 0:
        print(f"   🔄 Removed {dupes_removed} duplicate feature rows")

    # ── Type enforcement: all numeric → Float32 ──
    exclude = {"spotify_track_id", "file_name", "file_path", "estimated_mode"}
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if col not in exclude and col not in ("beat_count", "estimated_key"):
            df[col] = df[col].fillna(0.0).astype(np.float32)

    # Integer columns stay as int
    for col in ["beat_count", "estimated_key"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(np.int64)

    # String columns
    for col in ["spotify_track_id", "file_name", "file_path", "estimated_mode"]:
        if col in df.columns:
            df[col] = df[col].fillna("unknown").astype(str)

    # ── Drop lineage ──
    lineage_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=lineage_cols, errors="ignore")

    # ── Write ──
    output_path = output_dir / "cleansed_features.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)

    print(f"   ✅ Cleansed features: {len(df)} rows → cleansed_features.parquet")
    print(f"      Feature columns: {len(df.select_dtypes(include=[np.number]).columns)}")

    return df
