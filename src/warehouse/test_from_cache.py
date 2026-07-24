"""Tests for the D-60 cache→gold exporter. Synthetic cache; the tripwires guard
the regression CLASSES the design named (a twin leaking into dim_tracks; the
82-col fact contract; the grain that must NOT be reproduced)."""

from __future__ import annotations

import pytest

from ..store import dedup
from ..store.cache import FeatureCache
from ..store.test_perceptual import _club, _folk
from . import from_cache


@pytest.fixture
def cache(tmp_path):
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'g.db'}")
    metas = []
    # 3 clean canonical tracks (source-validated)
    for i in range(3):
        c.upsert(f"club{i}", _club(i), time_signature=4)
        metas.append({"spotify_track_id": f"club{i}", "track_name": f"Club {i}",
                      "artist_names": "DJ Loud", "primary_artist_id": "arLOUD",
                      "duration_ms": 200_000})
        c.remember_provenance(spotify_track_id=f"club{i}", youtube_url=f"https://y/{i}")
    # a TWIN of club0 (same recording, distinct id) — must NOT reach dim_tracks
    c.upsert("twin0", _club(0), time_signature=4)
    metas.append({"spotify_track_id": "twin0", "track_name": "Club 0",
                  "artist_names": "DJ Loud", "primary_artist_id": "arLOUD",
                  "duration_ms": 200_000})
    c.remember_provenance(spotify_track_id="twin0", youtube_url="https://y/twin")
    # an UNVALIDATED track (no provenance) — withheld, must NOT reach dim_tracks
    c.upsert("unval0", _folk(0), time_signature=3)
    metas.append({"spotify_track_id": "unval0", "track_name": "Folk 0",
                  "artist_names": "Quiet Folk", "primary_artist_id": "arFOLK",
                  "duration_ms": 180_000})
    c.remember_meta(metas)
    c.remember_artists([
        {"artist_id": "arLOUD", "artist_name": "DJ Loud", "genres": "house"},
        {"artist_id": "arFOLK", "artist_name": "Quiet Folk", "genres": "folk"}])
    # the twin flag is set by the O3 dedup pass, not the meta dict — set it directly
    with c._Session() as s:
        from ..store.models import TrackMeta
        s.get(TrackMeta, "twin0").duplicate_of = "club0"
        s.commit()
    return c


def test_dim_tracks_is_canonical_only(cache):
    ids = set(from_cache.build_dim_tracks(cache)["spotify_track_id"])
    assert ids == {"club0", "club1", "club2"}          # twin + unvalidated excluded


def test_dim_tracks_has_zero_dupe_clusters(cache):
    # THE regression: a twin leaking into dim_tracks would re-trip DUPLICATE_TRACKS
    dt = from_cache.build_dim_tracks(cache)
    records = [dedup.DedupRecord(track_id=r["spotify_track_id"], title=r["track_name"],
                                 artist=r["artist_names"], duration_ms=r["duration_ms"])
               for _, r in dt.iterrows()]
    assert dedup.find_duplicate_clusters(records) == []


def test_fact_copies_exactly_the_cache_feature_keys(cache):
    # fact-level contract parity: the fact carries EVERY cache feature key
    # (minus the 2 non-feature path keys) and invents none. On live data this
    # set is the frozen 82; on the synthetic fixture it's smaller — the
    # invariant (verbatim copy, no drift) is what matters and holds on both.
    fact = from_cache.build_fact_track_features(cache)
    added_meta = {"spotify_track_id", "track_name", "artist_names",
                  "primary_artist_name", "duration_ms"}
    fact_feature_keys = set(fact.columns) - added_meta
    sample = next(iter(cache.all_features().values()))
    expected = set(sample) - {"file_name", "file_path"}
    assert fact_feature_keys == expected                 # no extras, no drops


def test_fact_has_no_time_range_grain(cache):
    # the grain guard: reproducing (track x time_range) for a user-agnostic
    # corpus would fabricate per-user ranks — the serving fact is track-grain.
    fact = from_cache.build_fact_track_features(cache)
    assert "time_range" not in fact.columns and "rank" not in fact.columns
    assert len(fact) == len(set(fact["spotify_track_id"])) == 3   # one row per track


def test_export_is_deterministic(cache, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    from_cache.export_gold(cache, a)
    from_cache.export_gold(cache, b)
    for name in ("dim_tracks", "fact_track_features", "dim_artists"):
        assert (a / f"{name}.parquet").read_bytes() == (b / f"{name}.parquet").read_bytes()


def test_export_leaves_the_drift_plane_untouched(cache, tmp_path):
    # the exporter writes ONLY the catalog tables; a pre-existing
    # fact_listening_features must survive (it's the historical drift plane).
    (tmp_path).mkdir(exist_ok=True)
    drift = tmp_path / "fact_listening_features.parquet"
    from_cache.build_fact_track_features(cache).head(1).to_parquet(drift)  # a stand-in
    before = drift.read_bytes()
    from_cache.export_gold(cache, tmp_path)
    assert drift.read_bytes() == before
