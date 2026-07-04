"""
src.ingestion — Spotify API Ingestion Layer (2026 Compliant)
=============================================================
Pulls user personalization data and track metadata from the surviving
Spotify Web API endpoints, serializes to Parquet with the spotify_track_id
bridge key for joining with local DSP features.

Architecture:
    auth.py             → PKCE OAuth (the ONLY auth flow — no client secret)
    guardrails.py       → Blocks deprecated endpoints, strips removed fields
    fetchers.py         → High-level data fetchers (top items, metadata, playlists)
    audio_downloader.py → YouTube → MP3 acquisition (Phase 1)
    serializer.py       → Parquet persistence with bridge key

Quick Start:
    >>> from src.ingestion import get_user_spotify, fetch_top_tracks
    >>> sp = get_user_spotify()          # PKCE auth (opens browser first time)
    >>> df = fetch_top_tracks(sp=sp)     # your top 50 tracks (medium_term)
    >>> from src.ingestion import save_metadata_to_parquet
    >>> save_metadata_to_parquet(df)      # → data/embeddings/spotify_metadata.parquet

Full Pipeline:
    >>> from src.ingestion import fetch_all_top_items, save_top_items_to_parquet
    >>> data = fetch_all_top_items()
    >>> save_top_items_to_parquet(data)

Audio Download:
    >>> from src.ingestion import download_audio_for_tracks
    >>> summary = download_audio_for_tracks(data["tracks"])
"""

# Authentication
from .auth import get_user_spotify

# Guardrails
from .guardrails import (
    safe_api_call,
    strip_deprecated_fields,
    throttle,
    DeprecatedEndpointError,
)

# Data Fetchers
from .fetchers import (
    fetch_top_tracks,
    fetch_top_artists,
    fetch_all_top_items,
    fetch_artists_by_ids,
    fetch_track_metadata,
    fetch_batch_metadata,
    fetch_user_playlists,
    fetch_playlist_tracks,
    search_tracks,
    fetch_user_profile,
)

# Audio Download (Phase 1)
from .audio_downloader import (
    DownloadConfig,
    download_audio_for_tracks,
    download_track_audio,
    resolve_youtube_url,
    should_skip_download,
)

# Serialization
from .serializer import (
    save_metadata_to_parquet,
    save_top_items_to_parquet,
    load_metadata_parquet,
    get_track_ids_from_parquet,
)

__all__ = [
    # Auth
    "get_user_spotify",
    # Guardrails
    "safe_api_call", "strip_deprecated_fields", "throttle", "DeprecatedEndpointError",
    # Fetchers
    "fetch_top_tracks", "fetch_top_artists", "fetch_all_top_items",
    "fetch_artists_by_ids",
    "fetch_track_metadata", "fetch_batch_metadata",
    "fetch_user_playlists", "fetch_playlist_tracks",
    "search_tracks", "fetch_user_profile",
    # Audio Download (Phase 1)
    "DownloadConfig",
    "download_audio_for_tracks",
    "download_track_audio",
    "resolve_youtube_url",
    "should_skip_download",
    # Serialization
    "save_metadata_to_parquet", "save_top_items_to_parquet",
    "load_metadata_parquet", "get_track_ids_from_parquet",
]
