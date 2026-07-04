"""
test_warehouse.py — Warehouse Layer Tests (synthetic data only)
================================================================
Covers the Cleansed artists build and the genre-enriched dim_artists —
the path that feeds the taste map's genre overlay (SPEC P1).

Per project convention: synthetic DataFrames only, no API calls, no real
warehouse required.
"""

import numpy as np
import pandas as pd
import pytest

from src.warehouse.cleansed import build_cleansed_artists
from src.warehouse.modeled import _build_dim_artists


def _staged_artists(landed_at: str, rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["_landed_at"] = landed_at
    df["_source"] = "spotify_api"
    df["_snapshot_label"] = f"test_{landed_at}"
    return df


class TestBuildCleansedArtists:
    def test_empty_staging_returns_empty(self, tmp_path):
        result = build_cleansed_artists(staging_dir=tmp_path, output_dir=tmp_path)
        assert result.empty

    def test_dedupes_by_artist_id_keeping_latest(self, tmp_path):
        old = _staged_artists("2026-01-01T00:00:00", [
            {"artist_id": "a1", "artist_name": "Old Name", "genres": "rock",
             "num_genres": 1, "followers": 10, "image_url": None},
        ])
        new = _staged_artists("2026-02-01T00:00:00", [
            {"artist_id": "a1", "artist_name": "New Name", "genres": "rock, indie",
             "num_genres": 2, "followers": 20, "image_url": None},
        ])
        old.to_parquet(tmp_path / "artists_raw_old.parquet", index=False)
        new.to_parquet(tmp_path / "artists_raw_new.parquet", index=False)

        result = build_cleansed_artists(staging_dir=tmp_path, output_dir=tmp_path)
        assert len(result) == 1
        assert result.iloc[0]["artist_name"] == "New Name"
        assert result.iloc[0]["genres"] == "rock, indie"

    def test_mixed_shapes_top_and_backfill_rows(self, tmp_path):
        # top-artists rows carry time_range/rank; backfill rows don't —
        # both must collapse to identity columns without error.
        top = _staged_artists("2026-01-01T00:00:00", [
            {"artist_id": "a1", "artist_name": "Ranked", "genres": "punk",
             "num_genres": 1, "followers": 5, "image_url": None,
             "time_range": "short_term", "rank": 1},
        ])
        backfill = _staged_artists("2026-01-02T00:00:00", [
            {"artist_id": "a2", "artist_name": "Backfilled", "genres": "",
             "num_genres": 0, "followers": 0, "image_url": None},
        ])
        top.to_parquet(tmp_path / "artists_raw_a.parquet", index=False)
        backfill.to_parquet(tmp_path / "artists_raw_b.parquet", index=False)

        result = build_cleansed_artists(staging_dir=tmp_path, output_dir=tmp_path)
        assert len(result) == 2
        assert "time_range" not in result.columns  # identity grain only
        assert "rank" not in result.columns
        assert "_landed_at" not in result.columns  # lineage dropped

    def test_types_and_null_handling(self, tmp_path):
        staged = _staged_artists("2026-01-01T00:00:00", [
            {"artist_id": "a1", "artist_name": "X", "genres": None,
             "num_genres": None, "followers": None, "image_url": None},
        ])
        staged.to_parquet(tmp_path / "artists_raw_x.parquet", index=False)

        result = build_cleansed_artists(staging_dir=tmp_path, output_dir=tmp_path)
        row = result.iloc[0]
        assert row["genres"] == ""                      # null genres → empty string
        assert row["num_genres"] == 0
        assert result["followers"].dtype == np.int64
        # writes the parquet artifact
        assert (tmp_path / "cleansed_artists.parquet").exists()


class TestDimArtistsEnrichment:
    def _tracks(self):
        return pd.DataFrame([
            {"spotify_track_id": "t1", "primary_artist_id": "a1",
             "primary_artist_name": "Artist One", "time_range": "short_term"},
            {"spotify_track_id": "t2", "primary_artist_id": "a2",
             "primary_artist_name": "Artist Two", "time_range": "long_term"},
        ])

    def test_enriched_with_genres_when_available(self):
        artists = pd.DataFrame([
            {"artist_id": "a1", "artist_name": "Artist One",
             "genres": "garage rock, punk", "num_genres": 2,
             "followers": 100, "image_url": ""},
        ])
        dim = _build_dim_artists(self._tracks(), artists)
        assert len(dim) == 2  # every referenced primary artist has a row
        a1 = dim[dim["artist_id"] == "a1"].iloc[0]
        a2 = dim[dim["artist_id"] == "a2"].iloc[0]
        assert a1["genres"] == "garage rock, punk"
        assert a2["genres"] == ""  # missing from cleansed_artists → empty, not NaN

    def test_fallback_without_cleansed_artists(self):
        dim = _build_dim_artists(self._tracks(), None)
        assert len(dim) == 2
        assert "genres" not in dim.columns  # legacy shape preserved

    def test_empty_tracks_returns_empty(self):
        assert _build_dim_artists(pd.DataFrame(), None).empty


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
