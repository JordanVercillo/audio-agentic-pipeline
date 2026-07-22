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
    build_cluster_profile,
    build_corpus_facts,
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


# ── K2.0: corpus_facts ───────────────────────────────────────────────────────
def _semantic_frames(corpus):
    perc = compute_perceptual(corpus)
    tc = build_track_card(corpus, perc)
    ar = build_artist_rollup(corpus, perc)
    return perc, tc, ar


def test_corpus_facts_parity_and_valid_only_stats(corpus):
    _, tc, ar = _semantic_frames(corpus)
    cf = build_corpus_facts(tc, ar).iloc[0]
    assert cf["n_tracks"] == 9 and cf["n_feature_valid"] == 8   # broken row counted, not hidden
    assert cf["n_artists"] == 2
    # acoustic stats over VALID rows only — the −180 dBFS dead row can't tilt them
    valid = tc[tc["feature_valid"]]
    assert cf["median_tempo"] == round(float(valid["tempo"].median()), 1)
    assert cf["median_tempo"] > 1.0
    assert cf["built_at_utc"] and cf["version"] == tc["version"].iloc[0]
    assert build_corpus_facts(pd.DataFrame(), ar).empty          # empty in → no mart


# ── K2.0: cluster_profile ────────────────────────────────────────────────────
def test_cluster_profile_absent_without_a_model(corpus):
    _, tc, _ = _semantic_frames(corpus)
    assert build_cluster_profile(corpus, tc).empty   # no trained model → no mart


def test_cluster_profile_from_a_trained_model(corpus):
    from .clusters import train_song_clusters
    trained = train_song_clusters(corpus)
    assert trained is not None
    _, tc, _ = _semantic_frames(corpus)
    cp = build_cluster_profile(corpus, tc)
    assert len(cp) == trained["k"]
    assert (cp["label"] != "").all()                          # every cluster is named
    assert int(cp["n_assigned"].sum()) <= len(tc)             # never past the corpus
    assert ((cp["share_of_corpus"] >= 0) & (cp["share_of_corpus"] <= 1)).all()
    assert (cp["model_id"] == trained["model_id"]).all()
    # a populated cluster carries real acoustic means
    populated = cp[cp["n_assigned"] > 0]
    assert not populated.empty and populated["mean_tempo"].notna().all()


# ── K2.0: the audit tripwires (positive AND negative) ────────────────────────
def _write_semantic_marts(tmp_path, corpus, *, drop_card_row=False,
                          wrong_fact=False, bad_share=False):
    from .clusters import train_song_clusters
    from .perceptual import catalog_frame, compute_feature_stats
    train_song_clusters(corpus)
    perc, tc, ar = _semantic_frames(corpus)
    cf = build_corpus_facts(tc, ar)
    cp = build_cluster_profile(corpus, tc)
    if drop_card_row:
        tc = tc.iloc[1:]                       # a key in perceptual but not the card
    if wrong_fact:
        cf.loc[0, "n_tracks"] = 999
    if bad_share:
        cp.loc[0, "share_of_corpus"] = 1.7
    marts = tmp_path / "marts"
    marts.mkdir()
    perc.to_parquet(marts / "track_perceptual.parquet", index=False)
    catalog_frame().to_parquet(marts / "feature_catalog.parquet", index=False)
    compute_feature_stats(perc).to_parquet(marts / "feature_stats.parquet", index=False)
    tc.to_parquet(marts / "track_card.parquet", index=False)
    ar.to_parquet(marts / "artist_rollup.parquet", index=False)
    cf.to_parquet(marts / "corpus_facts.parquet", index=False)
    cp.to_parquet(marts / "cluster_profile.parquet", index=False)
    return marts


def _audit():
    from .test_perceptual import _load_audit_module
    return _load_audit_module()


def test_audit_semantic_marts_green_when_coherent(corpus, tmp_path):
    report, _, errors, flags = _audit().check_marts(_write_semantic_marts(tmp_path, corpus))
    # the fixture's broken row trips the (independent, pre-existing)
    # FEATURE_DISTRIBUTION check — the K2.0 flags themselves must read green
    for flag in ("PLANE_COHERENCE", "SEMANTIC_PARITY", "CLUSTER_PROFILE_DRIFT"):
        assert flags[flag] is False, flag
    assert not errors
    assert report["track_card"]["rows"] == 9 and report["corpus_facts"]["rows"] == 1


def test_audit_catches_plane_incoherence(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, drop_card_row=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["PLANE_COHERENCE"] is True
    assert any("PLANE_COHERENCE" in w for w in warnings)


def test_audit_catches_semantic_parity_break(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, wrong_fact=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["SEMANTIC_PARITY"] is True
    assert any("999" in w for w in warnings)


def test_audit_catches_cluster_profile_drift(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, bad_share=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["CLUSTER_PROFILE_DRIFT"] is True
    assert any("share_of_corpus" in w for w in warnings)
