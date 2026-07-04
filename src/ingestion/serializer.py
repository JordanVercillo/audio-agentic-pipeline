"""
serializer.py — Spotify Metadata → Parquet Persistence
========================================================
Saves ingested Spotify metadata to Parquet format with strict typing.
This is the ingestion layer's counterpart to src/dsp/serializer.py.

Both serializers write Parquet files with the spotify_track_id bridge key,
enabling downstream joins:

    ingestion/serializer → metadata.parquet ─┐
                                              ├─ JOIN ON spotify_track_id
    dsp/serializer → features.parquet ────────┘

Reference: 03_data_orchestrator.md — "The Bridging Key"
"""

from pathlib import Path
from typing import Optional, Union

import pandas as pd

try:
    import pyarrow  # noqa: F401 — verify import
except ImportError:
    raise ImportError("PyArrow required: pip install pyarrow>=14.0.0") from None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEFAULT OUTPUT PATHS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_METADATA_PATH = _DATA_DIR / "embeddings" / "spotify_metadata.parquet"
DEFAULT_TOP_ITEMS_PATH = _DATA_DIR / "embeddings" / "top_items.parquet"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SAVE METADATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_metadata_to_parquet(
    df: pd.DataFrame,
    output_path: Optional[Union[str, Path]] = None,
    append: bool = True,
) -> Path:
    """
    Save a DataFrame of Spotify track metadata to Parquet.

    Enforces:
        - spotify_track_id column must exist (the bridge key)
        - Deduplicates by spotify_track_id on append (keeps latest)
        - Parent directories created automatically

    Args:
        df:          DataFrame from fetchers (fetch_top_tracks, fetch_batch_metadata, etc.)
        output_path: Path to .parquet file. Defaults to data/embeddings/spotify_metadata.parquet.
        append:      If True and file exists, append new rows (deduplicated).

    Returns:
        Path to the written Parquet file.

    Raises:
        ValueError: If spotify_track_id column is missing.
    """
    if "spotify_track_id" not in df.columns:
        raise ValueError(
            "DataFrame must contain 'spotify_track_id' column. "
            "This is the mandatory bridge key per 03_data_orchestrator.md."
        )

    output_path = Path(output_path or DEFAULT_METADATA_PATH).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if append and output_path.exists():
        df_existing = pd.read_parquet(output_path)
        df_combined = pd.concat([df_existing, df], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["spotify_track_id"], keep="last")
        df_combined.to_parquet(output_path, engine="pyarrow", index=False)
        n_new = len(df_combined) - len(df_existing)
        print(f"   📝 Appended {n_new} new rows → {output_path.name} "
              f"(total: {len(df_combined)})")
    else:
        df.to_parquet(output_path, engine="pyarrow", index=False)
        print(f"   💾 Saved {len(df)} rows → {output_path.name}")

    return output_path


def save_top_items_to_parquet(
    data: dict[str, pd.DataFrame],
    output_dir: Optional[Union[str, Path]] = None,
) -> dict[str, Path]:
    """
    Save the output of fetch_all_top_items() to separate Parquet files.

    Creates:
        - top_tracks.parquet  (all time ranges combined)
        - top_artists.parquet (all time ranges combined)

    Args:
        data:       Dict from fetch_all_top_items() with "tracks" and "artists" keys.
        output_dir: Directory for output files. Defaults to data/embeddings/.

    Returns:
        Dict of {name: Path} for each written file.
    """
    output_dir = Path(output_dir or _DATA_DIR / "embeddings").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    if "tracks" in data and not data["tracks"].empty:
        tracks_path = output_dir / "top_tracks.parquet"
        data["tracks"].to_parquet(tracks_path, engine="pyarrow", index=False)
        print(f"   💾 Saved {len(data['tracks'])} top tracks → {tracks_path.name}")
        paths["tracks"] = tracks_path

    if "artists" in data and not data["artists"].empty:
        artists_path = output_dir / "top_artists.parquet"
        data["artists"].to_parquet(artists_path, engine="pyarrow", index=False)
        print(f"   💾 Saved {len(data['artists'])} top artists → {artists_path.name}")
        paths["artists"] = artists_path

    return paths


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  READ-BACK UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_metadata_parquet(
    path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Load a metadata Parquet file back into a DataFrame."""
    path = Path(path or DEFAULT_METADATA_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")
    df = pd.read_parquet(path, engine="pyarrow")
    print(f"   📂 Loaded {len(df)} rows from {path.name}")
    return df


def get_track_ids_from_parquet(
    path: Optional[Union[str, Path]] = None,
) -> list[str]:
    """Extract the list of spotify_track_ids from a metadata Parquet file."""
    df = load_metadata_parquet(path)
    ids = df["spotify_track_id"].dropna().unique().tolist()
    print(f"   🔑 {len(ids)} unique track IDs")
    return ids
