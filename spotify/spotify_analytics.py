"""
spotify_analytics.py — Comprehensive Spotify Analytics Engine
==============================================================

⚠️  DEPRECATED — This module is superseded by the Temporal Audio Pipeline.

Migration Guide:
    - Track Metadata    → audio-agentic-pipeline/src/ingestion/fetchers.py
    - User Top Items    → audio-agentic-pipeline/src/ingestion/fetchers.fetch_all_top_items()
    - DSP Features      → audio-agentic-pipeline/src/dsp/feature_extractor.py
    - Data Warehouse    → audio-agentic-pipeline/src/warehouse/ (Medallion architecture)
    - Taste Analysis    → audio-agentic-pipeline/src/analysis/drift.py

This file is retained for reference. New development should use the
audio-agentic-pipeline modules, which provide 2026-compliant API access,
distributed processing (PySpark), and agent-friendly data schemas.

Original Modules:
    1. Track Metadata         — fetch_track_metadata(), fetch_batch_metadata()
    2. Popularity Prediction  — build_popularity_dataset(), train_popularity_model()
    3. User Top Items EDA     — fetch_user_top_items(), build_listening_dashboard()
"""

import time
import warnings
from collections import deque
from datetime import datetime
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

import spotipy

# Local auth helpers
from spotify_config import get_client_credentials_spotify, get_user_spotify

warnings.filterwarnings("ignore", category=FutureWarning)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _safe_api_call(func, *args, label: str = "API call", **kwargs):
    """
    Wraps a spotipy call with graceful error handling.
    Returns (data, error_msg). If the call fails with 403/404,
    returns (None, human-readable message) instead of crashing.
    """
    try:
        result = func(*args, **kwargs)
        return result, None
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status in (403, 404):
            msg = (
                f"⚠️  RESTRICTED — {label}\n"
                f"   HTTP {e.http_status}: This endpoint requires Extended Quota Mode.\n"
                f"   Your app is in Development Mode (post-Nov 2024 restriction).\n"
                f"   Skipping gracefully."
            )
            print(msg)
            return None, msg
        raise  # re-raise unexpected errors
    except Exception as e:
        msg = f"❌ Unexpected error in {label}: {e}"
        print(msg)
        return None, msg


def _throttle(delay: float = 0.1):
    """Simple rate-limit pause between API calls."""
    time.sleep(delay)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODULE 1: TRACK METADATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_track_metadata(track_id: str, sp: Optional[spotipy.Spotify] = None) -> dict:
    """
    Fetches comprehensive metadata for a single track, enriched with
    artist and album details.

    Returns a flat dictionary suitable for DataFrame conversion.
    """
    if sp is None:
        sp = get_client_credentials_spotify()

    # ── Track ──
    track, err = _safe_api_call(sp.track, track_id, label=f"GET /tracks/{track_id}")
    if track is None:
        return {"error": err}

    # ── Primary artist ──
    primary_artist_id = track["artists"][0]["id"]
    artist, _ = _safe_api_call(sp.artist, primary_artist_id, label=f"GET /artists/{primary_artist_id}")
    _throttle()

    # ── Album ──
    album_id = track["album"]["id"]
    album, _ = _safe_api_call(sp.album, album_id, label=f"GET /albums/{album_id}")
    _throttle()

    # ── Build flat record ──
    record = {
        # Track core
        "track_id": track["id"],
        "track_name": track["name"],
        "track_popularity": track["popularity"],
        "explicit": track["explicit"],
        "duration_ms": track["duration_ms"],
        "disc_number": track["disc_number"],
        "track_number": track["track_number"],
        "is_local": track["is_local"],
        "preview_url": track.get("preview_url"),
        "external_url": track["external_urls"].get("spotify"),
        "isrc": track.get("external_ids", {}).get("isrc"),
        # All artists
        "artist_names": ", ".join(a["name"] for a in track["artists"]),
        "artist_ids": ", ".join(a["id"] for a in track["artists"]),
        "num_artists": len(track["artists"]),
        # Primary artist enriched
        "primary_artist_id": primary_artist_id,
        "primary_artist_name": track["artists"][0]["name"],
        "artist_popularity": artist["popularity"] if artist else None,
        "artist_followers": artist["followers"]["total"] if artist else None,
        "artist_genres": ", ".join(artist.get("genres", [])) if artist else None,
        "num_genres": len(artist.get("genres", [])) if artist else 0,
        # Album enriched
        "album_id": album_id,
        "album_name": track["album"]["name"],
        "album_type": track["album"]["album_type"],
        "album_popularity": album["popularity"] if album else None,
        "album_total_tracks": album["total_tracks"] if album else track["album"].get("total_tracks"),
        "album_release_date": album["release_date"] if album else track["album"].get("release_date"),
        "album_label": album.get("label") if album else None,
        # Derived features
        "is_single": track["album"]["album_type"] == "single",
        "track_position_ratio": (
            track["track_number"] / max(1, album["total_tracks"])
            if album else None
        ),
    }

    # Parse release date → album age in days
    rd = record["album_release_date"]
    if rd:
        try:
            if len(rd) == 4:         # "2012"
                dt = datetime(int(rd), 1, 1)
            elif len(rd) == 7:       # "2012-10"
                dt = datetime(int(rd[:4]), int(rd[5:7]), 1)
            else:                    # "2012-10-01"
                dt = datetime.strptime(rd, "%Y-%m-%d")
            record["album_age_days"] = (datetime.now() - dt).days
        except Exception:
            record["album_age_days"] = None
    else:
        record["album_age_days"] = None

    return record


def fetch_batch_metadata(track_ids: list[str], sp: Optional[spotipy.Spotify] = None) -> pd.DataFrame:
    """
    Fetches metadata for a list of track IDs and returns a DataFrame.
    Includes a progress indicator for large batches.
    """
    if sp is None:
        sp = get_client_credentials_spotify()

    records = []
    total = len(track_ids)
    for i, tid in enumerate(track_ids):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"   Fetching {i + 1}/{total}...", end="\r")
        rec = fetch_track_metadata(tid, sp=sp)
        records.append(rec)
        _throttle(0.15)

    print(f"   ✅ Fetched {total} tracks.")
    df = pd.DataFrame(records)
    return df


def display_track_card(record: dict):
    """Pretty-prints a single track record as a rich card."""
    if "error" in record:
        print(record["error"])
        return

    print("┌─────────────────────────────────────────────────┐")
    print(f"│ 🎵  {record['track_name']:<44}│")
    print("├─────────────────────────────────────────────────┤")
    print(f"│  Artist     │ {record['primary_artist_name']:<32} │")
    print(f"│  Album      │ {record['album_name'][:32]:<32} │")
    print(f"│  Popularity │ {'█' * (record['track_popularity'] // 5)} {record['track_popularity']}/100{' ' * max(0, 18 - record['track_popularity'] // 5)}│")
    print(f"│  Explicit   │ {'Yes 🔞' if record['explicit'] else 'No  ✅':<32} │")
    dur_min = record['duration_ms'] // 60000
    dur_sec = (record['duration_ms'] % 60000) // 1000
    print(f"│  Duration   │ {dur_min}:{dur_sec:02d}{' ' * 28}│")
    print(f"│  Released   │ {str(record.get('album_release_date', 'N/A')):<32} │")
    if record.get("artist_genres"):
        genres = record["artist_genres"][:45]
        print(f"│  Genres     │ {genres:<32} │")
    print(f"│  Followers  │ {record.get('artist_followers', 0):>12,}{' ' * 19}│")
    print("└─────────────────────────────────────────────────┘")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODULE 2: POPULARITY PREDICTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_popularity_dataset(track_ids: list[str], sp: Optional[spotipy.Spotify] = None) -> pd.DataFrame:
    """
    Builds a modeling-ready DataFrame from a list of track IDs.
    All features come from unrestricted endpoints (tracks, artists, albums).
    """
    print("📊 Building popularity dataset...")
    df = fetch_batch_metadata(track_ids, sp=sp)

    # Select numeric/usable features
    feature_cols = [
        "duration_ms", "explicit", "disc_number", "track_number",
        "num_artists", "artist_popularity", "artist_followers", "num_genres",
        "album_popularity", "album_total_tracks", "is_single",
        "track_position_ratio", "album_age_days",
    ]

    # Ensure boolean → int
    for col in ["explicit", "is_single"]:
        if col in df.columns:
            df[col] = df[col].astype(int)

    # Keep only rows without errors
    if "error" in df.columns:
        df = df[df["error"].isna()].drop(columns=["error"])

    available_features = [c for c in feature_cols if c in df.columns]

    print(f"   Features available: {len(available_features)}/{len(feature_cols)}")
    print(f"   Rows: {len(df)}")

    return df


def train_popularity_model(
    df: pd.DataFrame,
    target: str = "track_popularity",
    test_size: float = 0.2,
    random_state: int = 42,
) -> dict:
    """
    Trains a Random Forest regressor to predict track popularity.
    Returns a dict with model, metrics, feature importances, and figures.
    """
    feature_cols = [
        "duration_ms", "explicit", "disc_number", "track_number",
        "num_artists", "artist_popularity", "artist_followers", "num_genres",
        "album_popularity", "album_total_tracks", "is_single",
        "track_position_ratio", "album_age_days",
    ]

    available = [c for c in feature_cols if c in df.columns]
    df_model = df[available + [target]].dropna()

    if len(df_model) < 10:
        print(f"⚠️  Only {len(df_model)} rows after dropping NaN — need at least 10 for modeling.")
        return {"error": "insufficient data"}

    X = df_model[available]
    y = df_model[target]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    model = RandomForestRegressor(
        n_estimators=100, max_depth=8, random_state=random_state, n_jobs=-1
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    print(f"\n📈 Popularity Model Results")
    print(f"   MAE:  {mae:.2f}")
    print(f"   R²:   {r2:.3f}")
    print(f"   Train: {len(X_train)} | Test: {len(X_test)}")

    # ── Feature Importance Plot ──
    importances = pd.Series(model.feature_importances_, index=available).sort_values(ascending=True)

    fig_imp, ax_imp = plt.subplots(figsize=(10, 6))
    fig_imp.patch.set_facecolor("#0d1117")
    ax_imp.set_facecolor("#0d1117")
    bars = ax_imp.barh(importances.index, importances.values, color="#58a6ff", edgecolor="#1f6feb", linewidth=0.5)
    ax_imp.set_xlabel("Importance", color="#c9d1d9")
    ax_imp.set_title("Feature Importances — Track Popularity", color="#f0f6fc", fontsize=14, fontweight="bold")
    ax_imp.tick_params(colors="#c9d1d9")
    for spine in ax_imp.spines.values():
        spine.set_color("#30363d")
    plt.tight_layout()
    plt.show()

    # ── Actual vs Predicted ──
    fig_pred, ax_pred = plt.subplots(figsize=(8, 8))
    fig_pred.patch.set_facecolor("#0d1117")
    ax_pred.set_facecolor("#0d1117")
    ax_pred.scatter(y_test, y_pred, alpha=0.6, color="#7ee787", edgecolors="#238636", s=50)
    ax_pred.plot([0, 100], [0, 100], "--", color="#f85149", alpha=0.7, linewidth=1)
    ax_pred.set_xlabel("Actual Popularity", color="#c9d1d9", fontsize=12)
    ax_pred.set_ylabel("Predicted Popularity", color="#c9d1d9", fontsize=12)
    ax_pred.set_title("Actual vs Predicted", color="#f0f6fc", fontsize=14, fontweight="bold")
    ax_pred.tick_params(colors="#c9d1d9")
    for spine in ax_pred.spines.values():
        spine.set_color("#30363d")
    plt.tight_layout()
    plt.show()

    return {
        "model": model,
        "mae": mae,
        "r2": r2,
        "feature_importances": importances,
        "fig_importance": fig_imp,
        "fig_predicted": fig_pred,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODULE 3: USER TOP ITEMS EDA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_user_top_items(
    item_type: str = "artists",
    time_range: str = "medium_term",
    limit: int = 50,
    sp: Optional[spotipy.Spotify] = None,
) -> pd.DataFrame:
    """
    Fetches the current user's top artists or tracks.

    Requires Authorization Code flow (OAuth login).
    Note: Under Development Mode, this only works for users added to your Spotify Developer app whitelist (max 25).
    
    item_type: 'artists' or 'tracks'
    time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (years)
    """
    if sp is None:
        sp = get_user_spotify()

    results, err = _safe_api_call(
        sp.current_user_top_artists if item_type == "artists" else sp.current_user_top_tracks,
        limit=limit, time_range=time_range,
        label=f"GET /me/top/{item_type} ({time_range})"
    )

    if results is None:
        return pd.DataFrame()

    if item_type == "artists":
        records = []
        for a in results.get("items", []):
            records.append({
                "name": a["name"],
                "id": a["id"],
                "popularity": a["popularity"],
                "followers": a["followers"]["total"],
                "genres": ", ".join(a.get("genres", [])),
                "image_url": a["images"][0]["url"] if a.get("images") else None,
                "time_range": time_range,
            })
    else:
        records = []
        for t in results.get("items", []):
            records.append({
                "name": t["name"],
                "id": t["id"],
                "popularity": t["popularity"],
                "artist": t["artists"][0]["name"],
                "album": t["album"]["name"],
                "duration_ms": t["duration_ms"],
                "explicit": t["explicit"],
                "time_range": time_range,
            })

    df = pd.DataFrame(records)
    print(f"   ✅ Fetched {len(df)} top {item_type} ({time_range})")
    return df


def build_listening_dashboard(sp: Optional[spotipy.Spotify] = None):
    """
    Builds a comprehensive listening profile dashboard across all time ranges.
    Requires OAuth (user login).
    """
    if sp is None:
        sp = get_user_spotify()

    time_ranges = ["short_term", "medium_term", "long_term"]
    range_labels = {"short_term": "Last 4 Weeks", "medium_term": "Last 6 Months", "long_term": "All Time"}

    # Fetch all top artists across time ranges
    print("🎧 Building listening dashboard...\n")
    all_artists = []
    all_tracks = []

    for tr in time_ranges:
        artists_df = fetch_user_top_items("artists", tr, sp=sp)
        tracks_df = fetch_user_top_items("tracks", tr, sp=sp)
        if not artists_df.empty:
            artists_df["rank"] = range(1, len(artists_df) + 1)
            all_artists.append(artists_df)
        if not tracks_df.empty:
            tracks_df["rank"] = range(1, len(tracks_df) + 1)
            all_tracks.append(tracks_df)
        _throttle(0.2)

    if not all_artists:
        print("⚠️  No top items data retrieved. Make sure OAuth authentication succeeded.")
        return {}

    artists_combined = pd.concat(all_artists, ignore_index=True)
    tracks_combined = pd.concat(all_tracks, ignore_index=True) if all_tracks else pd.DataFrame()

    # ── Genre Frequency Heatmap ──
    fig_genre, axes = plt.subplots(1, 3, figsize=(18, 8))
    fig_genre.patch.set_facecolor("#0d1117")
    fig_genre.suptitle("🎵 Genre Distribution Across Time Ranges",
                       color="#f0f6fc", fontsize=16, fontweight="bold", y=1.02)

    for idx, tr in enumerate(time_ranges):
        ax = axes[idx]
        ax.set_facecolor("#0d1117")
        subset = artists_combined[artists_combined["time_range"] == tr]
        if subset.empty:
            continue

        # Explode genres
        genre_counts = {}
        for genres_str in subset["genres"]:
            for g in str(genres_str).split(", "):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1

        top = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        if top:
            names, counts = zip(*top)
            ax.barh(range(len(names)), counts, color="#58a6ff", edgecolor="#1f6feb")
            ax.set_yticks(range(len(names)))
            ax.set_yticklabels(names, fontsize=8, color="#c9d1d9")
            ax.invert_yaxis()

        ax.set_title(range_labels[tr], color="#f0f6fc", fontsize=12, fontweight="bold")
        ax.tick_params(colors="#c9d1d9")
        for spine in ax.spines.values():
            spine.set_color("#30363d")

    plt.tight_layout()
    plt.show()

    # ── Popularity Distribution ──
    if not tracks_combined.empty:
        fig_pop, ax_pop = plt.subplots(figsize=(10, 6))
        fig_pop.patch.set_facecolor("#0d1117")
        ax_pop.set_facecolor("#0d1117")

        colors_tr = {"short_term": "#7ee787", "medium_term": "#58a6ff", "long_term": "#f778ba"}
        for tr in time_ranges:
            subset = tracks_combined[tracks_combined["time_range"] == tr]
            if not subset.empty:
                ax_pop.hist(
                    subset["popularity"], bins=15, alpha=0.5,
                    label=range_labels[tr], color=colors_tr[tr], edgecolor="#30363d"
                )

        ax_pop.set_xlabel("Popularity Score", color="#c9d1d9")
        ax_pop.set_ylabel("Count", color="#c9d1d9")
        ax_pop.set_title("Track Popularity Distribution by Time Range",
                         color="#f0f6fc", fontsize=14, fontweight="bold")
        ax_pop.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9")
        ax_pop.tick_params(colors="#c9d1d9")
        for spine in ax_pop.spines.values():
            spine.set_color("#30363d")
        plt.tight_layout()
        plt.show()

    # ── Artist Churn Analysis ──
    print("\n📊 Artist Churn Analysis")
    print("─" * 40)
    for tr_a, tr_b in [("short_term", "medium_term"), ("medium_term", "long_term")]:
        a_set = set(artists_combined[artists_combined["time_range"] == tr_a]["name"])
        b_set = set(artists_combined[artists_combined["time_range"] == tr_b]["name"])
        overlap = a_set & b_set
        new = a_set - b_set
        dropped = b_set - a_set
        print(f"\n   {range_labels[tr_a]} vs {range_labels[tr_b]}:")
        print(f"   Overlap: {len(overlap)} artists")
        print(f"   New in {range_labels[tr_a]}: {len(new)}")
        if new:
            print(f"      → {', '.join(list(new)[:5])}{'...' if len(new) > 5 else ''}")

    # ── Diversity score ──
    print("\n🌈 Listening Diversity Scores")
    print("─" * 40)
    for tr in time_ranges:
        subset = artists_combined[artists_combined["time_range"] == tr]
        unique_genres = set()
        for g in subset["genres"]:
            for genre in str(g).split(", "):
                if genre.strip():
                    unique_genres.add(genre.strip())
        n_artists = len(subset)
        diversity = len(unique_genres) / max(n_artists, 1)
        print(f"   {range_labels[tr]}: {len(unique_genres)} genres / {n_artists} artists = {diversity:.2f}")

    return {
        "artists": artists_combined,
        "tracks": tracks_combined,
        "fig_genre": fig_genre,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  QUICK-START: Self-test
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 55)
    print("  🎵  SPOTIFY ANALYTICS ENGINE — Quick Test")
    print("=" * 55)

    sp = get_client_credentials_spotify()

    # Test 1: Track metadata
    print("\n━━━ TEST 1: Track Metadata ━━━")
    madness = fetch_track_metadata("0c4IEciLCDdXEhhKxj4ThA", sp=sp)
    display_track_card(madness)

    print("\n" + "=" * 55)
    print("  ✅  All tests completed!")
    print("=" * 55)
