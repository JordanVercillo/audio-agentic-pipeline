"""
fetchers.py — Spotify Data Fetchers (2026 Compliant)
=====================================================
High-level functions for pulling user and public data from the
surviving Spotify API endpoints.

Allowed Surface Area (per 01_spotify_api_guardrails.md):
    ✔ GET /me/top/{type}          — Personalization (our primary signal)
    ✔ GET /me/player              — Current playback
    ✔ GET /me/playlists           — User playlists
    ✔ GET /playlists/{id}/tracks  — Playlist contents
    ✔ GET /search                 — Search
    ✔ GET /me                     — User profile
    ✔ GET /tracks/{id}            — Track metadata
    ✔ GET /artists/{id}           — Artist metadata
    ✔ GET /albums/{id}            — Album metadata

Every function enforces:
    - Guardrail-checked API calls (no deprecated endpoints)
    - spotify_track_id as the universal key on all track records
    - `popularity` rides along as OPTIONAL fetched context (deprecated-not-
      removed upstream, journal #20) — absent-safe, never an ML input
"""

from datetime import datetime
from typing import Optional

import pandas as pd
import spotipy

from .auth import get_user_spotify
from .guardrails import safe_api_call, strip_deprecated_fields, throttle

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  USER TOP ITEMS (/me/top/{type})
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_top_tracks(
    time_range: str = "medium_term",
    limit: int = 50,
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Fetch the current user's top tracks for a given time range.

    This is our primary personalization signal — the surviving endpoint
    that tells us WHAT a user listens to. Combined with local DSP
    extraction on corresponding audio files, we rebuild the full
    acoustic profile that Spotify's deprecated endpoints used to provide.

    Args:
        time_range: One of:
            - "short_term"  (~last 4 weeks)
            - "medium_term" (~last 6 months, default)
            - "long_term"   (several years of data)
        limit: Number of tracks (1-50, API maximum is 50).
        sp:    Pre-authenticated Spotify client (PKCE). Created if None.

    Returns:
        DataFrame with columns:
            spotify_track_id, track_name, artist_names, artist_ids,
            album_name, album_id, duration_ms, explicit, disc_number,
            track_number, is_local, isrc, external_url, preview_url,
            time_range, rank
    """
    if sp is None:
        sp = get_user_spotify()

    results, err = safe_api_call(
        sp.current_user_top_tracks,
        limit=limit,
        time_range=time_range,
        label=f"GET /me/top/tracks ({time_range})",
    )

    if results is None:
        print(f"   ⚠️  Could not fetch top tracks ({time_range}): {err}")
        return pd.DataFrame()

    records = []
    for rank, track in enumerate(results.get("items", []), start=1):
        track = strip_deprecated_fields(track)
        records.append(_track_to_record(track, time_range=time_range, rank=rank))

    df = pd.DataFrame(records)
    print(f"   ✅ Fetched {len(df)} top tracks ({time_range})")
    return df


def fetch_top_artists(
    time_range: str = "medium_term",
    limit: int = 50,
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Fetch the current user's top artists for a given time range.

    Args:
        time_range: "short_term", "medium_term", or "long_term".
        limit:      Number of artists (1-50).
        sp:         Pre-authenticated Spotify client (PKCE).

    Returns:
        DataFrame with columns:
            artist_id, artist_name, genres, num_genres, followers,
            image_url, time_range, rank
    """
    if sp is None:
        sp = get_user_spotify()

    results, err = safe_api_call(
        sp.current_user_top_artists,
        limit=limit,
        time_range=time_range,
        label=f"GET /me/top/artists ({time_range})",
    )

    if results is None:
        print(f"   ⚠️  Could not fetch top artists ({time_range}): {err}")
        return pd.DataFrame()

    records = []
    for rank, artist in enumerate(results.get("items", []), start=1):
        artist = strip_deprecated_fields(artist)
        records.append({
            "artist_id": artist["id"],
            "artist_name": artist["name"],
            "genres": ", ".join(artist.get("genres", [])),
            "num_genres": len(artist.get("genres", [])),
            "followers": artist["followers"]["total"],
            "image_url": artist["images"][0]["url"] if artist.get("images") else None,
            "time_range": time_range,
            "rank": rank,
        })

    df = pd.DataFrame(records)
    print(f"   ✅ Fetched {len(df)} top artists ({time_range})")
    return df


def fetch_all_top_items(
    sp: Optional[spotipy.Spotify] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch top tracks AND artists across ALL three time ranges.

    Returns a dictionary with four DataFrames:
        {
            "tracks":  combined top tracks (all time ranges, with rank),
            "artists": combined top artists (all time ranges, with rank),
            "tracks_short_term":  just short_term tracks,
            ... etc (for convenience)
        }

    This is the primary function for building a comprehensive
    listening profile in a single call.
    """
    if sp is None:
        sp = get_user_spotify()

    print("🎧 Fetching personalization data across all time ranges...\n")

    time_ranges = ["short_term", "medium_term", "long_term"]
    all_tracks = []
    all_artists = []
    result = {}

    for tr in time_ranges:
        tracks_df = fetch_top_tracks(time_range=tr, sp=sp)
        artists_df = fetch_top_artists(time_range=tr, sp=sp)
        throttle(0.2)

        if not tracks_df.empty:
            all_tracks.append(tracks_df)
            result[f"tracks_{tr}"] = tracks_df
        if not artists_df.empty:
            all_artists.append(artists_df)
            result[f"artists_{tr}"] = artists_df

    result["tracks"] = pd.concat(all_tracks, ignore_index=True) if all_tracks else pd.DataFrame()
    result["artists"] = pd.concat(all_artists, ignore_index=True) if all_artists else pd.DataFrame()

    t_count = len(result["tracks"])
    a_count = len(result["artists"])
    print(f"\n   📊 Total: {t_count} track entries, {a_count} artist entries")

    return result


def fetch_artists_by_ids(
    artist_ids: list[str],
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Batch-fetch artist metadata for arbitrary artist IDs (GET /artists?ids=…).

    Why this exists: top TRACKS are made by artists who aren't always in the
    user's top ARTISTS list, so genre coverage from fetch_top_artists alone
    is partial. One batch call per 50 IDs fills the gap — dim_artists (and
    everything downstream: taste-map genre overlay, insights, RAG) gets
    complete genre metadata.

    Args:
        artist_ids: Spotify artist IDs (deduplicated internally).
        sp:         Pre-authenticated Spotify client (PKCE). Created if None.

    Returns:
        DataFrame with the same identity/genre columns as fetch_top_artists
        (no time_range/rank — these are backfill rows, not ranked top items).
    """
    ids = [a for a in dict.fromkeys(artist_ids) if a]  # dedupe, keep order
    if not ids:
        return pd.DataFrame()

    if sp is None:
        sp = get_user_spotify()

    records = []
    for i in range(0, len(ids), 50):  # API maximum is 50 per request
        batch = ids[i:i + 50]
        results, err = safe_api_call(
            sp.artists, batch,
            label=f"GET /artists?ids=… (batch of {len(batch)})",
        )
        if results is None:
            print(f"   ⚠️  Artist batch fetch failed: {err}")
            continue

        for artist in results.get("artists", []):
            if artist is None:
                continue  # unknown/removed ID — API returns null in its slot
            artist = strip_deprecated_fields(artist)
            records.append({
                "artist_id": artist["id"],
                "artist_name": artist["name"],
                "genres": ", ".join(artist.get("genres", [])),
                "num_genres": len(artist.get("genres", [])),
                "followers": artist.get("followers", {}).get("total", 0),
                "image_url": artist["images"][0]["url"] if artist.get("images") else None,
            })
        throttle(0.2)

    df = pd.DataFrame(records)
    print(f"   ✅ Backfilled metadata for {len(df)} artists ({len(ids)} requested)")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRACK METADATA ENRICHMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_track_metadata(
    track_id: str,
    sp: Optional[spotipy.Spotify] = None,
) -> dict:
    """
    Fetch comprehensive metadata for a single track, enriched with
    artist and album details. All deprecated fields are stripped.

    This is the 2026-compliant version of the function from
    projects/spotify/spotify_analytics.py. Key differences:
        - No popularity fields (stripped by guardrails)
        - Uses safe_api_call for all network calls
        - spotify_track_id is always present as the bridging key

    Args:
        track_id: Spotify track ID (e.g., "0c4IEciLCDdXEhhKxj4ThA").
        sp:       Pre-authenticated Spotify client (PKCE). Created if None.

    Returns:
        Flat dictionary suitable for DataFrame conversion.
        Contains {"error": msg} if the fetch fails.
    """
    if sp is None:
        sp = get_user_spotify()

    # ── Fetch track ──
    track, err = safe_api_call(sp.track, track_id, label=f"GET /tracks/{track_id}")
    if track is None:
        return {"error": err}
    track = strip_deprecated_fields(track)

    # ── Fetch primary artist ──
    primary_artist_id = track["artists"][0]["id"]
    artist, _ = safe_api_call(sp.artist, primary_artist_id, label=f"GET /artists/{primary_artist_id}")
    if artist:
        artist = strip_deprecated_fields(artist)
    throttle()

    # ── Fetch album ──
    album_id = track["album"]["id"]
    album, _ = safe_api_call(sp.album, album_id, label=f"GET /albums/{album_id}")
    if album:
        album = strip_deprecated_fields(album)
    throttle()

    # ── Build flat record ──
    record = {
        # Bridge key — mandatory per 03_data_orchestrator.md
        "spotify_track_id": track["id"],
        # Track core (no popularity — removed in 2026)
        "track_name": track["name"],
        "explicit": track["explicit"],
        "duration_ms": track["duration_ms"],
        "disc_number": track["disc_number"],
        "track_number": track["track_number"],
        "is_local": track["is_local"],
        "preview_url": track.get("preview_url"),
        "external_url": track["external_urls"].get("spotify"),
        "isrc": track.get("external_ids", {}).get("isrc"),
        # Artists
        "artist_names": ", ".join(a["name"] for a in track["artists"]),
        "artist_ids": ", ".join(a["id"] for a in track["artists"]),
        "num_artists": len(track["artists"]),
        "primary_artist_id": primary_artist_id,
        "primary_artist_name": track["artists"][0]["name"],
        "artist_followers": artist["followers"]["total"] if artist else None,
        "artist_genres": ", ".join(artist.get("genres", [])) if artist else None,
        "num_genres": len(artist.get("genres", [])) if artist else 0,
        # Album
        "album_id": album_id,
        "album_name": track["album"]["name"],
        "album_type": track["album"]["album_type"],
        "album_total_tracks": album["total_tracks"] if album else track["album"].get("total_tracks"),
        "album_release_date": album["release_date"] if album else track["album"].get("release_date"),
        "album_label": album.get("label") if album else None,
        # Derived
        "is_single": track["album"]["album_type"] == "single",
        "track_position_ratio": (
            track["track_number"] / max(1, album["total_tracks"])
            if album else None
        ),
    }

    # Parse release date → album age in days
    _enrich_album_age(record)

    return record


def fetch_batch_metadata(
    track_ids: list[str],
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Fetch metadata for a list of track IDs and return a DataFrame.

    Each row contains the full enriched metadata with spotify_track_id
    as the bridge key for joining with DSP features.

    Args:
        track_ids: List of Spotify track IDs.
        sp:        Pre-authenticated Spotify client.

    Returns:
        DataFrame with one row per track.
    """
    if sp is None:
        sp = get_user_spotify()

    records = []
    total = len(track_ids)
    for i, tid in enumerate(track_ids):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"   Fetching {i + 1}/{total}...", end="\r")
        rec = fetch_track_metadata(tid, sp=sp)
        records.append(rec)
        throttle(0.15)

    print(f"   ✅ Fetched {total} tracks.")
    df = pd.DataFrame(records)

    # Drop error rows
    if "error" in df.columns:
        n_errors = df["error"].notna().sum()
        if n_errors > 0:
            print(f"   ⚠️  {n_errors} tracks had errors and were dropped.")
        df = df[df["error"].isna()].drop(columns=["error"])

    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PLAYLISTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_user_playlists(
    sp: Optional[spotipy.Spotify] = None,
    limit: int = 50,
) -> pd.DataFrame:
    """
    Fetch the current user's playlists.

    Note per guardrails: track counts are accessed via playlist.items.total,
    NOT playlist.tracks.total (which is deprecated).
    """
    if sp is None:
        sp = get_user_spotify()

    results, err = safe_api_call(
        sp.current_user_playlists,
        limit=limit,
        label="GET /me/playlists",
    )

    if results is None:
        return pd.DataFrame()

    records = []
    for pl in results.get("items", []):
        records.append({
            "playlist_id": pl["id"],
            "playlist_name": pl["name"],
            "description": pl.get("description", ""),
            "owner_id": pl["owner"]["id"],
            "owner_name": pl["owner"].get("display_name", ""),
            "public": pl.get("public"),
            "collaborative": pl.get("collaborative", False),
            # 2026 change: use tracks.total (spotipy still returns this key)
            "track_count": pl["tracks"]["total"],
            "snapshot_id": pl.get("snapshot_id"),
            "image_url": pl["images"][0]["url"] if pl.get("images") else None,
        })

    df = pd.DataFrame(records)
    print(f"   ✅ Fetched {len(df)} playlists")
    return df


def fetch_playlist_tracks(
    playlist_id: str,
    sp: Optional[spotipy.Spotify] = None,
    limit: int = 100,
) -> pd.DataFrame:
    """
    Fetch all tracks from a playlist, handling pagination.

    Returns a DataFrame with spotify_track_id as the bridge key,
    plus playlist-specific metadata (added_at, added_by, position).
    """
    if sp is None:
        sp = get_user_spotify()

    records = []
    offset = 0
    position = 0

    while True:
        results, err = safe_api_call(
            sp.playlist_items,
            playlist_id,
            limit=min(limit, 100),
            offset=offset,
            label=f"GET /playlists/{playlist_id}/tracks (offset={offset})",
        )

        if results is None:
            break

        items = results.get("items", [])
        if not items:
            break

        for item in items:
            track = item.get("track")
            if track is None or track.get("id") is None:
                position += 1
                continue  # skip local files or unavailable tracks

            track = strip_deprecated_fields(track)
            rec = _track_to_record(track)
            rec["added_at"] = item.get("added_at")
            rec["added_by"] = item.get("added_by", {}).get("id")
            rec["playlist_position"] = position
            records.append(rec)
            position += 1

        # Pagination
        if results.get("next") is None:
            break
        offset += len(items)
        throttle(0.1)

    df = pd.DataFrame(records)
    print(f"   ✅ Fetched {len(df)} tracks from playlist {playlist_id}")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SEARCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def search_tracks(
    query: str,
    limit: int = 20,
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Search Spotify for tracks matching a query.

    Args:
        query: Search string (e.g., "Radiohead OK Computer", "genre:jazz").
        limit: Max results (1-50).
        sp:    Pre-authenticated Spotify client (PKCE). Created if None.

    Returns:
        DataFrame with spotify_track_id and metadata for each result.
    """
    if sp is None:
        sp = get_user_spotify()

    results, err = safe_api_call(
        sp.search,
        q=query,
        type="track",
        limit=limit,
        label=f"GET /search?q={query[:30]}...",
    )

    if results is None:
        return pd.DataFrame()

    records = []
    for rank, track in enumerate(results["tracks"]["items"], start=1):
        track = strip_deprecated_fields(track)
        rec = _track_to_record(track, rank=rank)
        rec["search_query"] = query
        records.append(rec)

    df = pd.DataFrame(records)
    print(f"   ✅ Search '{query[:30]}': {len(df)} results")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  USER PROFILE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_user_profile(
    sp: Optional[spotipy.Spotify] = None,
) -> dict:
    """Fetch the current user's Spotify profile."""
    if sp is None:
        sp = get_user_spotify()

    me, err = safe_api_call(sp.me, label="GET /me")
    if me is None:
        return {"error": err}

    return {
        "user_id": me["id"],
        "display_name": me.get("display_name"),
        "email": me.get("email"),
        "country": me.get("country"),
        "product": me.get("product"),  # "premium", "free", etc.
        "followers": me.get("followers", {}).get("total", 0),
        "image_url": me["images"][0]["url"] if me.get("images") else None,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _track_to_record(
    track: dict,
    time_range: Optional[str] = None,
    rank: Optional[int] = None,
) -> dict:
    """
    Convert a raw Spotify track object into a flat record dict.

    This is the canonical track normalization function. All fetcher
    functions route through this to ensure consistent column naming
    and the mandatory spotify_track_id bridge key.
    """
    record = {
        # ── Bridge key (mandatory per 03_data_orchestrator.md) ──
        "spotify_track_id": track["id"],
        # ── Track core ──
        "track_name": track["name"],
        "explicit": track["explicit"],
        "duration_ms": track["duration_ms"],
        "disc_number": track["disc_number"],
        "track_number": track["track_number"],
        "is_local": track.get("is_local", False),
        "preview_url": track.get("preview_url"),
        "external_url": track.get("external_urls", {}).get("spotify"),
        "isrc": track.get("external_ids", {}).get("isrc"),
        # ── Artists ──
        "artist_names": ", ".join(a["name"] for a in track.get("artists", [])),
        "artist_ids": ", ".join(a["id"] for a in track.get("artists", []) if a.get("id")),
        "num_artists": len(track.get("artists", [])),
        "primary_artist_name": track["artists"][0]["name"] if track.get("artists") else None,
        "primary_artist_id": track["artists"][0]["id"] if track.get("artists") else None,
        # ── Album ──
        "album_name": track.get("album", {}).get("name"),
        "album_id": track.get("album", {}).get("id"),
        "album_type": track.get("album", {}).get("album_type"),
        "album_release_date": track.get("album", {}).get("release_date"),
        # Album cover (not deprecated — present on the top-tracks response).
        "album_image_url": (track.get("album", {}).get("images") or [{}])[0].get("url"),
        # Deprecated-NOT-removed (verified live 2026-07-09; journal #20):
        # optional fetched CONTEXT — absent-safe, never an ML input.
        "popularity": track.get("popularity"),
    }

    if time_range:
        record["time_range"] = time_range
    if rank is not None:
        record["rank"] = rank

    return record


def _enrich_album_age(record: dict) -> None:
    """Parse album_release_date and add album_age_days to the record."""
    rd = record.get("album_release_date")
    if not rd:
        record["album_age_days"] = None
        return
    try:
        if len(rd) == 4:        # "2012"
            dt = datetime(int(rd), 1, 1)
        elif len(rd) == 7:      # "2012-10"
            dt = datetime(int(rd[:4]), int(rd[5:7]), 1)
        else:                   # "2012-10-01"
            dt = datetime.strptime(rd, "%Y-%m-%d")
        record["album_age_days"] = (datetime.now() - dt).days
    except Exception:
        record["album_age_days"] = None
