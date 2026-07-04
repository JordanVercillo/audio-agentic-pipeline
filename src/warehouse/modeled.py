"""
modeled.py — Star Schema (Medallion: Gold / Modeled)
=====================================================
Builds the final analytical layer: a star schema optimized for
AI agent queries and temporal taste analysis.

Star Schema Design:
    ┌──────────────────────┐
    │  dim_time_range      │
    │  ────────────────    │
    │  time_range_key (PK) │
    │  time_range_label    │
    │  window_description  │
    │  approx_days         │
    └────────┬─────────────┘
             │
    ┌────────┴─────────────────────────────────────────────┐
    │              fact_listening_features                   │
    │  ─────────────────────────────────────────────        │
    │  spotify_track_id + time_range (composite PK)        │
    │  rank                                                 │
    │  ── Track Metadata (denormalized for query speed) ── │
    │  track_name, artist_names, album_name, duration_ms   │
    │  ── DSP Features (77D) ──                            │
    │  tempo_bpm, rms_mean, zcr_mean, mfcc_mean_0..12     │
    │  chroma_mean_C..B, spectral_centroid_mean, ...       │
    │  harmonic_ratio, estimated_key, estimated_mode       │
    └────────┬──────────────────────────┬──────────────────┘
             │                          │
    ┌────────┴─────────────┐   ┌───────┴──────────────┐
    │  dim_tracks           │   │  dim_artists          │
    │  ────────────────     │   │  ────────────────     │
    │  spotify_track_id(PK) │   │  artist_id (PK)      │
    │  track_name           │   │  artist_name          │
    │  album_name           │   │  genres               │
    │  album_type           │   │  num_genres            │
    │  album_release_date   │   │  followers             │
    │  duration_ms          │   │  image_url             │
    │  explicit             │   └──────────────────────┘
    │  isrc                 │
    └───────────────────────┘

Why denormalize in the fact table?
    Agent-oriented design. An AI agent querying "What is Jordan's
    highest-energy track in short_term?" should get track_name in
    the result without needing to JOIN. We accept the storage overhead
    for query simplicity — this is a read-optimized analytical layer.

Column Descriptions (for AI agent consumption):
    Every column in the fact table includes a rich description so an
    agent can understand what it represents without human intervention.
    These descriptions are stored in the COLUMN_DESCRIPTIONS dict below.

Reference: Medallion Architecture — Gold/Modeled Layer
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COLUMN DESCRIPTIONS (Agent-Oriented Interface)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COLUMN_DESCRIPTIONS = {
    # ── Identifiers ──
    "spotify_track_id": "Unique Spotify track identifier. Universal join key across all tables.",
    "time_range": "Listening recency window: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (several years).",
    "rank": "User's listening rank within the time_range (1 = most listened). Lower rank = higher affinity.",

    # ── Track Metadata (denormalized) ──
    "track_name": "Song title as displayed on Spotify.",
    "artist_names": "Comma-separated list of all contributing artist names.",
    "primary_artist_name": "Lead/primary artist name.",
    "album_name": "Album title.",
    "duration_ms": "Track duration in milliseconds. Typical range: 120000–420000 (2–7 minutes).",
    "explicit": "True if track contains explicit lyrics.",

    # ── Rhythm Features ──
    "tempo_bpm": "Estimated tempo in beats per minute. Typical range: 60–200 BPM. Replaces Spotify's deprecated 'tempo' field.",
    "onset_strength_mean": "Mean onset detection strength. Higher = more rhythmically active. Proxy for danceability.",
    "onset_strength_std": "Variability of onset strength. High std = dynamic rhythm (e.g., jazz). Low std = steady beat (e.g., EDM).",
    "beats_per_sec": "Beat frequency. Derived from beat_count / duration_sec.",

    # ── Energy Features ──
    "rms_mean": "Root Mean Square energy (perceived loudness). Range: 0–1. Replaces Spotify's deprecated 'energy' field.",
    "rms_std": "Variability of loudness. High = dynamic range (classical). Low = compressed (pop/EDM).",
    "zcr_mean": "Zero Crossing Rate. High = noisy/percussive. Low = tonal/harmonic. Proxy for speechiness.",
    "zcr_std": "Variability of zero crossing rate.",

    # ── Timbre (MFCCs) ──
    "mfcc_mean_0": "MFCC coefficient 0 mean: overall spectral energy level.",
    "mfcc_mean_1": "MFCC coefficient 1 mean: spectral slope (bright vs. dark timbre).",
    "mfcc_mean_2": "MFCC coefficient 2 mean: second-order spectral shape.",

    # ── Spectral Shape ──
    "spectral_centroid_mean": "Center of mass of the spectrum (Hz). High = bright sound (cymbals). Low = dark sound (bass).",
    "spectral_centroid_std": "Variability of spectral centroid. High = timbral variety within the track.",
    "spectral_rolloff_mean": "Frequency below which 85% of spectral energy lies. Another brightness metric.",
    "harmonic_ratio": "Harmonic-to-total energy ratio (0–1). Near 1 = acoustic/harmonic (replaces Spotify 'acousticness'). Near 0 = percussive/noisy.",

    # ── Tonal Features ──
    "estimated_key": "Estimated musical key as pitch class (0=C, 1=C#, ..., 11=B). Replaces Spotify's deprecated 'key' field.",
    "estimated_mode": "Estimated mode: 'major' or 'minor'. Replaces Spotify's deprecated 'mode' field.",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DIMENSION TABLES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_dim_time_range() -> pd.DataFrame:
    """
    Build the time range dimension table.

    This is a static reference table — Spotify defines exactly
    three time ranges for the /me/top endpoint.
    """
    return pd.DataFrame([
        {
            "time_range_key": "short_term",
            "time_range_label": "Last 4 Weeks",
            "window_description": "Approximately the last 4 weeks of listening activity.",
            "approx_days": 28,
            "sort_order": 1,
        },
        {
            "time_range_key": "medium_term",
            "time_range_label": "Last 6 Months",
            "window_description": "Approximately the last 6 months of listening activity.",
            "approx_days": 180,
            "sort_order": 2,
        },
        {
            "time_range_key": "long_term",
            "time_range_label": "All Time",
            "window_description": "Several years of listening history. The most stable signal.",
            "approx_days": 1095,
            "sort_order": 3,
        },
    ])


def _build_dim_tracks(cleansed_tracks: pd.DataFrame) -> pd.DataFrame:
    """
    Build the track dimension table.

    Deduplicates across time ranges to produce one row per track
    with the richest available metadata (from the latest snapshot).
    """
    if cleansed_tracks.empty:
        return pd.DataFrame()

    dim_cols = [
        "spotify_track_id", "track_name", "artist_names", "primary_artist_name",
        "primary_artist_id", "album_name", "album_id", "album_type",
        "album_release_date", "duration_ms", "explicit", "is_local",
        "disc_number", "track_number", "num_artists", "isrc",
        "external_url", "preview_url",
    ]
    available = [c for c in dim_cols if c in cleansed_tracks.columns]

    dim = cleansed_tracks[available].drop_duplicates(
        subset=["spotify_track_id"], keep="first"
    )

    return dim.reset_index(drop=True)


def _build_dim_artists(
    cleansed_tracks: pd.DataFrame,
    cleansed_artists: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build the artist dimension table.

    Base population: every primary artist referenced by the track data
    (guarantees join coverage for the fact table). When the Cleansed
    artists table is available, each row is enriched with genre metadata
    (genres, num_genres, followers, image_url) — the taste map's genre
    overlay and the insight engine read genres from HERE.
    """
    if cleansed_tracks.empty:
        return pd.DataFrame()

    artist_cols = ["primary_artist_id", "primary_artist_name"]
    available = [c for c in artist_cols if c in cleansed_tracks.columns]

    if not available or "primary_artist_id" not in available:
        return pd.DataFrame()

    dim = cleansed_tracks[available].drop_duplicates(
        subset=["primary_artist_id"], keep="first"
    ).rename(columns={"primary_artist_id": "artist_id", "primary_artist_name": "artist_name"})

    # ── Genre enrichment from cleansed_artists (when present) ──
    if cleansed_artists is not None and not cleansed_artists.empty \
            and "artist_id" in cleansed_artists.columns:
        enrich_cols = [c for c in ["artist_id", "genres", "num_genres",
                                   "followers", "image_url"]
                       if c in cleansed_artists.columns]
        dim = dim.merge(cleansed_artists[enrich_cols], on="artist_id", how="left")
        if "genres" in dim.columns:
            dim["genres"] = dim["genres"].fillna("")
            covered = int((dim["genres"] != "").sum())
            print(f"   🎸 dim_artists genre coverage: {covered}/{len(dim)}")

    return dim.reset_index(drop=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FACT TABLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_fact_listening_features(
    cleansed_tracks: pd.DataFrame,
    cleansed_features: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build the fact table by joining tracks with their DSP features.

    Grain: one row per (spotify_track_id, time_range) pair.

    The same track appears multiple times if it shows up in multiple
    time ranges (e.g., a track in both short_term and long_term).
    The DSP features are repeated because they're intrinsic to the audio,
    but the rank and time_range differ — this is the temporal dimension
    that enables taste drift analysis.

    Join strategy:
        LEFT JOIN cleansed_tracks ON cleansed_features
        using spotify_track_id. Tracks without DSP features still
        appear (with NaN feature values) to preserve completeness.

    Args:
        cleansed_tracks:   Output of build_cleansed_tracks().
        cleansed_features: Output of build_cleansed_features().

    Returns:
        Fact table DataFrame.
    """
    if cleansed_tracks.empty:
        return pd.DataFrame()

    # Select track columns to keep in the fact table (denormalized)
    track_cols = [
        "spotify_track_id", "track_name", "artist_names",
        "primary_artist_name", "album_name", "duration_ms",
        "explicit", "time_range", "rank",
    ]
    available_track_cols = [c for c in track_cols if c in cleansed_tracks.columns]
    tracks_subset = cleansed_tracks[available_track_cols]

    if cleansed_features.empty:
        # No features yet — return tracks only
        print("   ⚠️  No features available — fact table contains metadata only.")
        return tracks_subset

    # ── JOIN ──
    # Features don't have time_range (they're time-independent),
    # so we join on track_id and the features repeat across time ranges.
    feature_cols_to_drop = ["file_name", "file_path"]
    features_subset = cleansed_features.drop(
        columns=[c for c in feature_cols_to_drop if c in cleansed_features.columns]
    )

    fact = tracks_subset.merge(
        features_subset,
        on="spotify_track_id",
        how="left",
    )

    return fact


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN BUILD FUNCTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_star_schema(
    cleansed_dir: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> dict[str, pd.DataFrame]:
    """
    Build the complete star schema from Cleansed layer data.

    Reads cleansed_tracks.parquet and cleansed_features.parquet,
    then produces:
        - fact_listening_features.parquet (grain: track × time_range)
        - dim_tracks.parquet (one row per track)
        - dim_artists.parquet (one row per artist)
        - dim_time_range.parquet (static reference)
        - column_descriptions.parquet (agent-readable metadata)

    Args:
        cleansed_dir: Override Cleansed directory path.
        output_dir:   Override Modeled directory path.

    Returns:
        Dict with keys: "fact", "dim_tracks", "dim_artists",
        "dim_time_range", "column_descriptions"
    """
    cleansed_dir = Path(cleansed_dir or CLEANSED_DIR).resolve()
    output_dir = Path(output_dir or MODELED_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("🏗️  Building star schema...\n")

    # ── Load Cleansed data ──
    tracks_path = cleansed_dir / "cleansed_tracks.parquet"
    features_path = cleansed_dir / "cleansed_features.parquet"
    artists_path = cleansed_dir / "cleansed_artists.parquet"

    cleansed_tracks = pd.DataFrame()
    cleansed_features = pd.DataFrame()
    cleansed_artists = pd.DataFrame()

    if tracks_path.exists():
        cleansed_tracks = pd.read_parquet(tracks_path, engine="pyarrow")
        print(f"   📂 Loaded {len(cleansed_tracks)} cleansed tracks")
    else:
        print(f"   ⚠️  {tracks_path.name} not found — run build_cleansed_tracks() first")

    if features_path.exists():
        cleansed_features = pd.read_parquet(features_path, engine="pyarrow")
        print(f"   📂 Loaded {len(cleansed_features)} cleansed features")
    else:
        print(f"   ⚠️  {features_path.name} not found — fact table will have metadata only")

    if artists_path.exists():
        cleansed_artists = pd.read_parquet(artists_path, engine="pyarrow")
        print(f"   📂 Loaded {len(cleansed_artists)} cleansed artists")
    else:
        print(f"   ⚠️  {artists_path.name} not found — dim_artists will lack genres")

    # ── Build tables ──
    dim_time_range = _build_dim_time_range()
    dim_tracks = _build_dim_tracks(cleansed_tracks)
    dim_artists = _build_dim_artists(cleansed_tracks, cleansed_artists)
    fact = _build_fact_listening_features(cleansed_tracks, cleansed_features)

    # ── Column descriptions (agent interface) ──
    col_desc_df = pd.DataFrame([
        {"column_name": k, "description": v}
        for k, v in COLUMN_DESCRIPTIONS.items()
    ])

    # ── Persist ──
    tables = {
        "fact_listening_features": fact,
        "dim_tracks": dim_tracks,
        "dim_artists": dim_artists,
        "dim_time_range": dim_time_range,
        "column_descriptions": col_desc_df,
    }

    for name, df in tables.items():
        if not df.empty:
            path = output_dir / f"{name}.parquet"
            df.to_parquet(path, engine="pyarrow", index=False)
            print(f"   ✅ {name}: {len(df)} rows → {path.name}")

    # ── Summary ──
    print(f"\n   📊 Star Schema Summary:")
    print(f"      Fact table rows:    {len(fact)}")
    print(f"      Unique tracks:      {len(dim_tracks)}")
    print(f"      Unique artists:     {len(dim_artists)}")
    print(f"      Time ranges:        {len(dim_time_range)}")
    print(f"      Column descriptions: {len(col_desc_df)}")

    if not fact.empty and "time_range" in fact.columns:
        print(f"\n   📊 Rows per time range:")
        for tr, count in fact["time_range"].value_counts().items():
            print(f"      {tr}: {count}")

    return {
        "fact": fact,
        "dim_tracks": dim_tracks,
        "dim_artists": dim_artists,
        "dim_time_range": dim_time_range,
        "column_descriptions": col_desc_df,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LOAD UTILITIES (for downstream consumers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_fact_table(
    modeled_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Load the fact_listening_features table from the Modeled layer."""
    modeled_dir = Path(modeled_dir or MODELED_DIR).resolve()
    path = modeled_dir / "fact_listening_features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Fact table not found: {path}. Run build_star_schema() first.")
    df = pd.read_parquet(path, engine="pyarrow")
    print(f"   📂 Loaded fact table: {len(df)} rows, {len(df.columns)} columns")
    return df


def load_dimension(
    dim_name: str,
    modeled_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Load a dimension table from the Modeled layer.

    Args:
        dim_name: One of "dim_tracks", "dim_artists", "dim_time_range",
                  "column_descriptions".

    Returns:
        The requested dimension DataFrame.
    """
    modeled_dir = Path(modeled_dir or MODELED_DIR).resolve()
    path = modeled_dir / f"{dim_name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Dimension '{dim_name}' not found: {path}.")
    df = pd.read_parquet(path, engine="pyarrow")
    print(f"   📂 Loaded {dim_name}: {len(df)} rows")
    return df


def get_column_descriptions(
    modeled_dir: Optional[Union[str, Path]] = None,
) -> dict[str, str]:
    """
    Return column descriptions as a dict for agent consumption.

    Usage by an AI agent:
        descriptions = get_column_descriptions()
        # descriptions["tempo_bpm"] → "Estimated tempo in beats per minute..."
    """
    try:
        df = load_dimension("column_descriptions", modeled_dir)
        return dict(zip(df["column_name"], df["description"]))
    except FileNotFoundError:
        return COLUMN_DESCRIPTIONS
