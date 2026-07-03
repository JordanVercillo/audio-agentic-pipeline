"""
staging.py — Raw Data Landing Layer (Medallion: Staging)
=========================================================
Lands raw API responses and raw DSP features into Parquet files
with lineage metadata (extraction timestamp, source, version).

Design Philosophy:
    Staging data is IMMUTABLE. Once landed, it is never modified.
    Downstream layers (Cleansed, Modeled) read from Staging and
    produce their own outputs. This enables full auditability and
    reprocessing from source.

Data Contract:
    - Every Staging file includes a `_landed_at` timestamp column
    - Every Staging file includes a `_source` column (e.g., "spotify_api", "dsp_local")
    - No transformations — data is landed exactly as received
    - Parquet format with pyarrow engine, snappy compression

Reference: Medallion Architecture — Bronze/Staging Layer
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import numpy as np

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STAGING_DIR = _PROJECT_ROOT / "data" / "warehouse" / "staging"


def land_staging_tracks(
    tracks_df: pd.DataFrame,
    output_dir: Optional[Union[str, Path]] = None,
    snapshot_label: Optional[str] = None,
) -> Path:
    """
    Land raw Spotify top tracks into the Staging layer.

    This function takes the raw output from `ingestion.fetch_top_tracks()`
    (or `fetch_all_top_items()["tracks"]`) and writes it to Staging with
    lineage metadata. No transformations are applied.

    Why snapshot_label?
        Each extraction run produces a point-in-time snapshot. The label
        (e.g., "2026-05-05_run1") allows us to track which run produced
        which data, enabling re-processing and A/B comparison of different
        extraction times.

    Args:
        tracks_df:      Raw tracks DataFrame from ingestion layer.
        output_dir:     Override for staging directory.
        snapshot_label: Human-readable label for this extraction run.

    Returns:
        Path to the written Parquet file.

    Schema expectations (input):
        spotify_track_id, track_name, artist_names, duration_ms,
        time_range, rank, ... (all columns from fetch_top_tracks)
    """
    output_dir = Path(output_dir or STAGING_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if tracks_df.empty:
        print("   ⚠️  Empty DataFrame — nothing to stage.")
        return output_dir

    # ── Add lineage metadata ──
    now = datetime.now(timezone.utc).isoformat()
    df = tracks_df.copy()
    df["_landed_at"] = now
    df["_source"] = "spotify_api"
    df["_snapshot_label"] = snapshot_label or f"snapshot_{now[:10]}"

    # ── Write to Parquet (append-safe via timestamped filenames) ──
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"tracks_raw_{ts}.parquet"
    output_path = output_dir / filename

    df.to_parquet(output_path, engine="pyarrow", index=False)

    print(f"   📥 Staged {len(df)} tracks → {filename}")
    print(f"      Time ranges: {df['time_range'].unique().tolist() if 'time_range' in df.columns else 'N/A'}")
    print(f"      Snapshot: {df['_snapshot_label'].iloc[0]}")

    return output_path


def land_staging_features(
    features_df: pd.DataFrame,
    output_dir: Optional[Union[str, Path]] = None,
    snapshot_label: Optional[str] = None,
) -> Path:
    """
    Land raw DSP features into the Staging layer.

    Takes the raw output from DSP feature extraction (via
    `dsp.serializer.save_features_to_parquet()` or a DataFrame
    built from TrackFeatures.to_summary_dict()) and writes it
    to Staging with lineage metadata.

    Args:
        features_df:    Raw DSP features DataFrame.
        output_dir:     Override for staging directory.
        snapshot_label: Label for this extraction run.

    Returns:
        Path to the written Parquet file.

    Schema expectations (input):
        spotify_track_id, file_name, duration_sec, tempo_bpm,
        rms_mean, mfcc_mean_0..12, chroma_mean_C..B, ... (77D features)
    """
    output_dir = Path(output_dir or STAGING_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if features_df.empty:
        print("   ⚠️  Empty DataFrame — nothing to stage.")
        return output_dir

    now = datetime.now(timezone.utc).isoformat()
    df = features_df.copy()
    df["_landed_at"] = now
    df["_source"] = "dsp_local"
    df["_snapshot_label"] = snapshot_label or f"snapshot_{now[:10]}"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"features_raw_{ts}.parquet"
    output_path = output_dir / filename

    df.to_parquet(output_path, engine="pyarrow", index=False)

    print(f"   📥 Staged {len(df)} feature rows → {filename}")

    return output_path


def land_staging_artists(
    artists_df: pd.DataFrame,
    output_dir: Optional[Union[str, Path]] = None,
    snapshot_label: Optional[str] = None,
) -> Path:
    """
    Land raw Spotify top artists into the Staging layer.

    Args:
        artists_df:     Raw artists DataFrame from ingestion layer.
        output_dir:     Override for staging directory.
        snapshot_label: Label for this extraction run.

    Returns:
        Path to the written Parquet file.
    """
    output_dir = Path(output_dir or STAGING_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if artists_df.empty:
        print("   ⚠️  Empty DataFrame — nothing to stage.")
        return output_dir

    now = datetime.now(timezone.utc).isoformat()
    df = artists_df.copy()
    df["_landed_at"] = now
    df["_source"] = "spotify_api"
    df["_snapshot_label"] = snapshot_label or f"snapshot_{now[:10]}"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"artists_raw_{ts}.parquet"
    output_path = output_dir / filename

    df.to_parquet(output_path, engine="pyarrow", index=False)

    print(f"   📥 Staged {len(df)} artists → {filename}")

    return output_path


def list_staging_files(
    staging_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Inventory all files in the Staging layer.

    Returns a DataFrame with file name, size, row count, and snapshot label
    for auditing and lineage tracking.
    """
    staging_dir = Path(staging_dir or STAGING_DIR).resolve()

    if not staging_dir.exists():
        return pd.DataFrame(columns=["file_name", "size_kb", "row_count", "snapshot_label"])

    records = []
    for f in sorted(staging_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, engine="pyarrow")
            records.append({
                "file_name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "row_count": len(df),
                "snapshot_label": df["_snapshot_label"].iloc[0] if "_snapshot_label" in df.columns else "unknown",
                "source": df["_source"].iloc[0] if "_source" in df.columns else "unknown",
                "landed_at": df["_landed_at"].iloc[0] if "_landed_at" in df.columns else "unknown",
            })
        except Exception as e:
            records.append({"file_name": f.name, "size_kb": 0, "row_count": 0, "snapshot_label": f"ERROR: {e}"})

    return pd.DataFrame(records)
