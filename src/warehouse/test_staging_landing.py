"""Q6 - the staging landing functions, tested rather than mocked.

`src/warehouse/staging.py` read 14.1% line coverage in the first CI baseline
(2026-07-31) and the reason is instructive: it IS live - `collection_extractor`
calls `land_staging_features` at `src/dsp/collection_extractor.py:355` - but its
only test mocks it (`_STAGING_PATCH` in `test_collection_extractor.py:223`).
Mocking the collaborator is right for testing the CALLER; it just means nobody
was testing the collaborator.

This matters beyond tidiness: `spark/parity_check.py` reads the staging layer,
so Phase 5's J2 parity work stands on these files' shape.

Synthetic only (ground rule 5): every frame is built here, nothing touches the
real warehouse.
"""
from __future__ import annotations

import pandas as pd
import pytest

from .staging import (
    land_staging_artists,
    land_staging_features,
    land_staging_tracks,
    list_staging_files,
)

BRIDGE = "spotify_track_id"


@pytest.fixture
def features() -> pd.DataFrame:
    return pd.DataFrame([
        {BRIDGE: f"trk{i:03d}", "tempo_bpm": 90.0 + i, "rms_mean": 0.1 + i / 100,
         "spectral_centroid_mean": 1800.0 + i, "dsp_version": "test-v1"}
        for i in range(5)
    ])


def test_features_land_as_parquet_keyed_on_the_bridge_key(features, tmp_path):
    """Parquet only, bridge key intact - ground rules 1 and 2, at the layer
    where a CSV would be easiest to reach for."""
    out = land_staging_features(features, output_dir=tmp_path)

    assert out.exists() and out.suffix == ".parquet", (
        f"staging landed something other than parquet: {out.name}")
    back = pd.read_parquet(out)
    assert BRIDGE in back.columns, "the bridge key did not survive landing"
    assert set(back[BRIDGE]) == set(features[BRIDGE])
    assert len(back) == len(features)


def test_landing_preserves_the_feature_values_it_was_given(features, tmp_path):
    """A landing step that silently rounds or retypes a feature would corrupt
    every downstream layer, and the bridge key would still look fine."""
    back = pd.read_parquet(land_staging_features(features, output_dir=tmp_path))
    merged = features.merge(back, on=BRIDGE, suffixes=("_in", "_out"))
    assert len(merged) == len(features)
    for col in ("tempo_bpm", "rms_mean", "spectral_centroid_mean"):
        pd.testing.assert_series_equal(
            merged[f"{col}_in"], merged[f"{col}_out"],
            check_names=False, check_dtype=False,
            obj=f"{col} changed while landing")


def test_snapshot_label_separates_landings(features, tmp_path):
    """Two landings must not collide - staging is append-of-snapshots, and a
    silent overwrite would make a re-run look like a no-op."""
    a = land_staging_features(features, output_dir=tmp_path, snapshot_label="a")
    b = land_staging_features(features, output_dir=tmp_path, snapshot_label="b")
    assert a != b, "two labelled snapshots landed on the same path"
    assert a.exists() and b.exists()


def test_tracks_and_artists_land_too(tmp_path):
    """The other two entry points `collection_extractor` and the pipeline use."""
    tracks = pd.DataFrame([{BRIDGE: "trk001", "name": "A", "artist": "X"},
                           {BRIDGE: "trk002", "name": "B", "artist": "Y"}])
    artists = pd.DataFrame([{"artist_id": "art1", "artist_name": "X"},
                            {"artist_id": "art2", "artist_name": "Y"}])
    tp = land_staging_tracks(tracks, output_dir=tmp_path)
    ap = land_staging_artists(artists, output_dir=tmp_path)
    assert tp.exists() and tp.suffix == ".parquet"
    assert ap.exists() and ap.suffix == ".parquet"
    assert BRIDGE in pd.read_parquet(tp).columns


def test_list_staging_files_finds_what_was_landed(features, tmp_path):
    """`spark/parity_check.py` discovers the layer this way; if listing misses a
    landed file, parity silently compares a subset."""
    land_staging_features(features, output_dir=tmp_path, snapshot_label="one")
    land_staging_features(features, output_dir=tmp_path, snapshot_label="two")
    found = list_staging_files(tmp_path)
    assert len(list(found)) >= 2, f"listing found {found}"


def test_empty_frame_does_not_land_a_lie(tmp_path):
    """An empty extraction must not produce a file that later reads as data."""
    empty = pd.DataFrame(columns=[BRIDGE, "tempo_bpm"])
    try:
        out = land_staging_features(empty, output_dir=tmp_path)
    except ValueError:
        return                            # refusing outright is also correct
    assert len(pd.read_parquet(out)) == 0, (
        "an empty landing produced rows out of nowhere")
