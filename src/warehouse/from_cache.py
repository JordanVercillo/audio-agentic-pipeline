"""
from_cache.py — materialize the batch gold plane from the live serving cache (D-60).

The project has two data planes: the LIVE serving plane (SQLite+WAL cache +
Parquet marts) that the app renders and grows, and the BATCH star-schema
(`data/warehouse/modeled/`) that the MCP server and taste map read. They had
diverged — the serving plane at the current canonical corpus, the batch plane
frozen at a Jul-4 snapshot of 118 tracks — which tripped the `DUPLICATE_TRACKS`
audit flag (near-dupes the serving layer's O3 dedup already resolves).

This is the one materialization path that unifies the CATALOG: it reads the
cache and writes a current, canonical `dim_tracks` + a track-grain
`fact_track_features`, so the gold catalog reflects the same deduped tracks the
app serves. Built DIRECTLY from the cache (not round-tripped through staging):
staging's contract is immutable raw API/DSP responses landed with lineage, and
the cache is already-cleansed, deduped, curated serving data — landing it as
"raw" would falsify provenance and `cleansed` would flatten unknown→0.0.

What it deliberately does NOT touch: `fact_listening_features` — its
(track × time_range) grain carries REAL per-user listening ranks from the Jul-4
top-tracks pulls and powers the taste map / insights / MCP temporal demo. The
serving corpus is user-agnostic (D-7); reproducing that grain for the grown
corpus would fabricate per-user rankings (REAL-data-only). So the drift plane
stays as an honest historical snapshot; the catalog is what unifies.

Ground rules held: bridge key `spotify_track_id` untouched; the frozen 77-dim
feature contract copied verbatim from the cache (never recomputed); Parquet +
pyarrow; deterministic (sorted by bridge key, no timestamps → byte-identical
reruns); atomic writes reuse the F1 per-pid `_write_atomic`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..store.perceptual import _write_atomic

# Feature-dict keys that are not part of the 82-col DSP contract (the fact drops
# them exactly as the existing `_build_fact_listening_features` does).
_NON_FEATURE_KEYS = ("file_name", "file_path")


def canonical_ids(cache: Any) -> list[str]:
    """The tracks that shape an aggregate — analyzed minus twins minus
    source-unvalidated (the one shared O3+B2 filter). Sorted, deterministic."""
    return sorted(set(cache.all_features()) - cache.excluded_from_aggregates())


def build_dim_tracks(cache: Any) -> pd.DataFrame:
    """One row per canonical track — the catalog dimension. Twin-free by
    construction, so the metadata dedup check finds zero clusters."""
    ids = set(canonical_ids(cache))
    durs = cache.all_durations_ms()
    # P4.6.6: the D-60 exporter narrowed dim_tracks to 6 columns, silently
    # dropping album_name / album_release_date / isrc that the old
    # `modeled.py` build carried. Nothing consumed them, so nothing failed —
    # but the documented star schema promised them, and the first
    # `SELECT album_release_date FROM dim_tracks` (an MCP query, a notebook)
    # would have been a KeyError. D-70 now captures the identity fields, so
    # the dimension can carry them honestly instead of being quietly thinner
    # than its own contract.
    ident = cache.all_track_identity()
    rows = []
    for r in cache.library_rows():                 # carries name/artist/primary_artist_id
        if r["id"] not in ids:
            continue
        artist = r.get("artist") or ""
        idt = ident.get(r["id"]) or {}
        rows.append({
            "spotify_track_id": r["id"],
            "track_name": r.get("name"),
            "artist_names": artist,
            "primary_artist_name": artist.split(",")[0].strip(),
            "primary_artist_id": r.get("primary_artist_id"),
            "duration_ms": durs.get(r["id"]),
            "album_name": idt.get("album_name"),
            "album_id": idt.get("album_id"),
            "album_type": idt.get("album_type"),
            "album_release_date": idt.get("album_release_date"),
            "isrc": idt.get("isrc"),
        })
    return pd.DataFrame(sorted(rows, key=lambda x: x["spotify_track_id"]))


def build_fact_track_features(cache: Any) -> pd.DataFrame:
    """Track-grain fact: the 82 DSP features + denormalized catalog metadata,
    one row per canonical track (NO time_range/rank — that grain is user-signal
    the serving corpus doesn't carry, and fabricating it is the REAL-data line).
    The feature values are copied verbatim from the frozen 77-dim vector."""
    ids = canonical_ids(cache)
    feats = cache.all_features()
    durs = cache.all_durations_ms()
    metas = cache.all_meta()
    rows = []
    for tid in ids:
        f = {k: v for k, v in feats[tid].items() if k not in _NON_FEATURE_KEYS}
        m = metas.get(tid, {})
        artist = m.get("artist_names") or ""
        rows.append({
            "spotify_track_id": tid,
            "track_name": m.get("track_name"),
            "artist_names": artist,
            "primary_artist_name": artist.split(",")[0].strip(),
            "duration_ms": durs.get(tid),
            **f,
        })
    return pd.DataFrame(rows)


def build_dim_artists(cache: Any) -> pd.DataFrame:
    """Artist dimension from the stored artist_meta — so the 730 tracks' artists
    resolve with genres/popularity (the genre overlay the taste map reads)."""
    rows = [{
        "artist_id": a.get("artist_id"),
        "artist_name": a.get("artist_name"),
        "genres": a.get("genres") or "",
        "followers": a.get("followers"),
        "popularity": a.get("popularity"),
        "image_url": a.get("image_url"),
    } for a in cache.all_artist_meta().values()]
    return pd.DataFrame(sorted(rows, key=lambda x: str(x["artist_id"])))


def export_gold(cache: Any, modeled_dir: Path) -> dict[str, int]:
    """Write the current catalog gold tables (atomic, deterministic). Leaves
    `fact_listening_features`, `dim_time_range`, `column_descriptions` and
    `cluster_assignments` untouched — the historical drift plane."""
    modeled_dir = Path(modeled_dir)
    modeled_dir.mkdir(parents=True, exist_ok=True)
    dim_tracks = build_dim_tracks(cache)
    fact = build_fact_track_features(cache)
    dim_artists = build_dim_artists(cache)
    _write_atomic(dim_tracks, modeled_dir / "dim_tracks.parquet")
    _write_atomic(fact, modeled_dir / "fact_track_features.parquet")
    _write_atomic(dim_artists, modeled_dir / "dim_artists.parquet")
    return {"dim_tracks": len(dim_tracks),
            "fact_track_features": len(fact),
            "dim_artists": len(dim_artists)}
