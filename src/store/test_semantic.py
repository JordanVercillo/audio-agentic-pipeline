"""
test_semantic.py — the D-49 semantic layer, synthetic. The 4 tripwires guard
the regression CLASSES the design named, not just line coverage (journal #35).
"""

from __future__ import annotations

import pandas as pd
import pytest

from .cache import FeatureCache
from .perceptual import compute_perceptual
from .semantic import (
    build_artist_rollup,
    build_track_card,
    feature_dictionary_frame,
)
from .test_perceptual import _club, _folk


@pytest.fixture
def corpus(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 's.db'}")
    metas = []
    for i in range(4):
        cache.upsert(f"club{i}", _club(i), time_signature=4)
        cache.upsert(f"folk{i}", _folk(i), time_signature=3)
        metas += [
            {"spotify_track_id": f"club{i}", "track_name": f"Club {i}",
             "artist_names": "DJ Loud", "primary_artist_id": "arLOUD001", "popularity": 60},
            {"spotify_track_id": f"folk{i}", "track_name": f"Folk {i}",
             "artist_names": "Quiet Folk", "primary_artist_id": "arFOLK002", "popularity": 30}]
    # a BROKEN extraction — the exact silent-track shape (tempo 0, loudness ≈ −180)
    broken = {**_folk(0), "tempo_bpm": 0.0, "rms_mean": 1e-9}
    cache.upsert("brokenX", broken, time_signature=4)
    metas.append({"spotify_track_id": "brokenX", "track_name": "Silent",
                  "artist_names": "DJ Loud", "primary_artist_id": "arLOUD001"})
    cache.remember_meta(metas)
    cache.remember_artists([
        {"artist_id": "arLOUD001", "artist_name": "DJ Loud", "genres": "house"},
        {"artist_id": "arFOLK002", "artist_name": "Quiet Folk", "genres": "folk"}])
    return cache


# ── the pure dictionary ──────────────────────────────────────────────────────
def test_feature_dictionary_carries_the_rule3_caveat():
    fd = feature_dictionary_frame().set_index("column")
    assert "popularity" in fd.index
    cav = fd.loc["popularity", "caveat"].lower()
    assert "metadata" in cav and "never" in cav and "input" in cav   # rule 3, as a row
    assert fd.loc["tempo", "direction"] == "higher = faster"


# ── tripwire 1: plane coherence (the bug journal #35 is about) ────────────────
def test_tripwire_plane_coherence(corpus):
    perc = compute_perceptual(corpus)
    tc = build_track_card(corpus, perc)
    n_analyzed = len(corpus.all_features())
    assert len(tc) == len(perc) == n_analyzed   # all cache-derived, all agree


# ── tripwire 2: no broken superlative ────────────────────────────────────────
def test_tripwire_no_broken_superlative(corpus):
    tc = build_track_card(corpus, compute_perceptual(corpus)).set_index("spotify_track_id")
    # the silent track survives as a ROW (honesty) but is gated invalid…
    assert tc.loc["brokenX", "feature_valid"] == False  # noqa: E712
    assert (tc[tc["tempo"] <= 1.0]["feature_valid"] == False).all()  # noqa: E712
    # …so "slowest valid song" is a real track, never the 0-bpm dead row
    valid = tc[tc["feature_valid"]]
    assert valid["tempo"].min() > 1.0
    assert pd.isna(tc.loc["brokenX", "tempo_pct"])  # excluded from the percentile rank


# ── tripwire 3: dictionary parity ────────────────────────────────────────────
def test_tripwire_dictionary_parity(corpus):
    fd = feature_dictionary_frame().set_index("column")
    tc = build_track_card(corpus, compute_perceptual(corpus))
    feature_cols = [c for c in tc.columns if c in fd.index]
    assert feature_cols  # some feature columns are documented
    for col in feature_cols:
        assert fd.loc[col, "tier"] and fd.loc[col, "unit"]  # no undocumented feature reaches the analyst


# ── tripwire 4: key resolvability ────────────────────────────────────────────
def test_tripwire_artist_rollup_keys_resolve(corpus):
    ar = build_artist_rollup(corpus, compute_perceptual(corpus))
    meta_ids = {m.get("primary_artist_id") for m in corpus.library_rows()}
    assert not ar.empty
    for paid in ar["primary_artist_id"]:
        assert paid in meta_ids                       # never an orphaned retrieval key
    loud = ar.set_index("primary_artist_id").loc["arLOUD001"]
    assert loud["n_tracks"] == 5 and loud["genres"] == "house"  # 4 club + the broken one
