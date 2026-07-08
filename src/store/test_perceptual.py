"""
test_perceptual.py — the perceptual-v1 transform, synthetic (VISION_SPECS F1).

Two acoustically-opposite blobs → the derived features must order them the
right way round; measured features must match exact math; sparse rows sit out.
"""

from __future__ import annotations

import math

import pytest

from .cache import FeatureCache
from .perceptual import (
    CATALOG,
    PERCEPTUAL_VERSION,
    catalog_frame,
    compute_perceptual,
    persist_perceptual,
)


def _club(i: float) -> dict:
    """Danceable club blob: ~120 bpm, loud, bright, punchy, regular pulse."""
    return {"tempo_bpm": 118 + i, "rms_mean": 0.30, "rms_std": 0.02,
            "zcr_mean": 0.09, "spectral_centroid_mean": 3000.0,
            "spectral_rolloff_mean": 6000.0, "spectral_flatness_mean": 0.05,
            "harmonic_ratio": 0.35, "onset_strength_mean": 3.0,
            "onset_strength_std": 0.5, "beats_per_sec": 2.0,
            "duration_sec": 200.0, "estimated_key": 7.0, "estimated_mode": "major"}


def _folk(i: float) -> dict:
    """Acoustic folk blob: slow, quiet, dark, harmonic, loose pulse."""
    return {"tempo_bpm": 62 + i, "rms_mean": 0.08, "rms_std": 0.05,
            "zcr_mean": 0.03, "spectral_centroid_mean": 1200.0,
            "spectral_rolloff_mean": 2500.0, "spectral_flatness_mean": 0.01,
            "harmonic_ratio": 0.85, "onset_strength_mean": 0.8,
            "onset_strength_std": 0.9, "beats_per_sec": 1.0,
            "duration_sec": 180.0, "estimated_key": 2.0, "estimated_mode": "minor"}


@pytest.fixture
def corpus(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'p.db'}")
    for i in range(5):
        cache.upsert(f"club{i}", _club(i))
        cache.upsert(f"folk{i}", _folk(i))
    cache.upsert("ghost", {"tempo_bpm": None})  # never-acquired track
    return cache


def test_measured_features_exact(corpus):
    df = compute_perceptual(corpus).set_index("spotify_track_id")
    row = df.loc["club0"]
    assert row["tempo"] == 118.0
    assert row["key"] == 7 and row["mode"] == 1.0          # "major" → 1
    assert df.loc["folk0", "mode"] == 0.0                  # "minor" → 0
    assert row["duration_sec"] == 200.0
    assert row["loudness_db"] == round(20 * math.log10(0.30), 2)  # exact math
    assert (df["version"] == PERCEPTUAL_VERSION).all()


def test_derived_features_order_the_blobs_correctly(corpus):
    df = compute_perceptual(corpus).set_index("spotify_track_id")
    club, folk = df.loc["club2"], df.loc["folk2"]
    assert club["energy"] > folk["energy"]                 # loud+punchy beats quiet
    assert club["danceability"] > folk["danceability"]     # 120bpm regular > 62bpm loose
    assert folk["acousticness"] > club["acousticness"]     # harmonic+dark beats bright
    assert club["brightness"] > folk["brightness"]
    assert folk["dynamics"] > club["dynamics"]             # rms_std 0.05 > 0.02
    for col in ("energy", "danceability", "acousticness", "speechiness",
                "brightness", "punch", "dynamics", "valence_proxy"):
        assert df[col].between(0, 1).all(), col            # calibrated range


def test_ghost_row_sits_out(corpus):
    df = compute_perceptual(corpus)
    assert len(df) == 10 and "ghost" not in set(df["spotify_track_id"])


def test_persist_and_read_back(corpus):
    df = compute_perceptual(corpus)
    n = persist_perceptual(corpus, df)
    assert n == 10
    got = corpus.get_perceptual(["club0", "ghost"])
    assert set(got) == {"club0"}
    assert got["club0"]["tempo"] == 118.0 and "danceability" in got["club0"]
    # idempotent rerun
    assert persist_perceptual(corpus, df) == 10
    assert len(corpus.all_perceptual()) == 10


def test_catalog_integrity():
    cat = catalog_frame()
    assert set(cat["tier"]) == {"measured", "derived", "experimental"}
    assert len(cat) == len(CATALOG) == cat["column"].nunique()
    # every catalog column is actually produced by the transform
    cache_cols = {"spotify_track_id", "version"}
    produced = set(compute_perceptual_cols())
    assert set(cat["column"]) <= produced - cache_cols
    # experimental features carry a caveat in their description
    exp = cat[cat["tier"] == "experimental"]
    assert all("proxy" in d.lower() or "heuristic" in d.lower()
               for d in exp["description"])


def compute_perceptual_cols() -> list[str]:
    """The transform's output columns, derived from a tiny in-memory run."""
    cache = FeatureCache(url="sqlite://")  # in-memory
    for i in range(4):
        cache.upsert(f"a{i}", _club(i))
        cache.upsert(f"b{i}", _folk(i))
    return list(compute_perceptual(cache).columns)


def test_empty_cache_returns_empty_frame(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'empty.db'}")
    df = compute_perceptual(cache)
    assert df.empty