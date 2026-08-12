"""The evaluation harness has to be evaluated too.

A metric that returns a low number for everything looks exactly like a model
that is bad at everything. So the first test here builds a retrieval model that
is PERFECT by construction and asserts the harness scores it near 1.0 — without
that, the live 0.05 could be the harness's floor rather than the model's
ceiling, and there would be no way to tell.

Synthetic only (ground rule 5): every fixture is built in-process.
"""
from __future__ import annotations

import numpy as np
import pytest

from .model_eval import (
    _recall,
    cluster_null_model,
    evaluate_similarity,
    playlist_truth,
)


class _FakeCache:
    """The four methods the harness touches, and nothing else."""

    def __init__(self, playlists, features, artists=None, popularity=None,
                 neighbours=None):
        self._playlists = playlists
        self._features = features
        self._artists = artists or {}
        self._pop = popularity or {}
        self._neighbours = neighbours or {}

    def all_features(self):
        return self._features

    def playlist_track_ids(self):
        return self._playlists

    def excluded_from_aggregates(self):
        return set()

    def library_rows(self):
        return [{"id": t, "primary_artist_id": self._artists.get(t),
                 "artist": self._artists.get(t, ""), "popularity": self._pop.get(t, 0)}
                for t in self._features]

    def similar(self, track_id, k=6):
        return [(t, float(i)) for i, t in enumerate(self._neighbours.get(track_id, []))][:k]


def _corpus(n=30):
    return {f"t{i:02d}": {"tempo_bpm": 100.0 + i} for i in range(n)}


# ── the metric itself ────────────────────────────────────────────────────────

def test_recall_denominator_cannot_punish_a_perfect_ranker():
    """With 40 relevant items and k=10 the best possible score must be 1.0."""
    relevant = {f"r{i}" for i in range(40)}
    ranked = [f"r{i}" for i in range(10)]
    assert _recall(ranked, relevant, 10) == 1.0
    assert _recall([], relevant, 10) == 0.0
    assert _recall(ranked, set(), 10) == 0.0


# ── the ground truth ─────────────────────────────────────────────────────────

def test_same_artist_pairs_are_excluded_as_leakage():
    """Two tracks by one artist are trivially close in acoustic space; counting
    them would mostly measure 'can we detect the same artist'."""
    feats = _corpus(4)
    playlists = {"p1": ["t00", "t01", "t02", "t03"]}
    artists = {"t00": "A", "t01": "A", "t02": "B", "t03": "C"}
    cache = _FakeCache(playlists, feats, artists=artists)

    truth = playlist_truth(cache)
    assert "t01" not in truth["t00"], "same-artist pair survived the leakage filter"
    assert {"t02", "t03"} <= truth["t00"]

    kept = playlist_truth(cache, exclude_same_artist=False)
    assert "t01" in kept["t00"], "the filter cannot be switched off"


def test_a_library_dump_is_not_treated_as_a_curation():
    """The live data holds one 876-track playlist whose signal is 'saved it',
    not 'these belong together'."""
    feats = _corpus(40)
    dump = {"big": [f"t{i:02d}" for i in range(40)]}
    cache = _FakeCache(dump, feats)
    assert playlist_truth(cache, max_playlist=20) == {}
    assert playlist_truth(cache, max_playlist=100) != {}


def test_unanalyzed_co_members_are_not_counted_against_the_model():
    """A track with no features cannot be retrieved, so requiring it would
    depress recall for a reason unrelated to the model."""
    feats = _corpus(3)                       # t00..t02 analyzed
    playlists = {"p1": ["t00", "t01", "NOPE"]}
    truth = playlist_truth(_FakeCache(playlists, feats))
    assert "NOPE" not in truth.get("t00", set())


# ── the harness end to end ───────────────────────────────────────────────────

def test_a_perfect_retriever_scores_near_one():
    """THE control. Without it, a low live score is unattributable: it could be
    the model, or it could be a harness that cannot score above 0.05."""
    feats = _corpus(12)
    playlists = {"p1": ["t00", "t01", "t02"], "p2": ["t03", "t04", "t05"]}
    artists = {t: t for t in feats}          # all different -> no leakage filter
    # an oracle: every seed's neighbours ARE its playlist co-members
    neighbours = {"t00": ["t01", "t02"], "t01": ["t00", "t02"], "t02": ["t00", "t01"],
                  "t03": ["t04", "t05"], "t04": ["t03", "t05"], "t05": ["t03", "t04"]}
    cache = _FakeCache(playlists, feats, artists=artists, neighbours=neighbours)

    res = evaluate_similarity(cache, ks=(1, 2), n_boot=50)
    assert res["n_seeds"] == 6
    assert res["model"]["recall@2"] == 1.0, res["model"]
    assert res["beats_popularity"] is True


def test_a_useless_retriever_scores_zero_and_says_so():
    """The other end of the range — the harness must be able to fail a model."""
    feats = _corpus(12)
    playlists = {"p1": ["t00", "t01", "t02"]}
    artists = {t: t for t in feats}
    # neighbours that are never co-members
    neighbours = {t: ["t09", "t10", "t11"] for t in ("t00", "t01", "t02")}
    cache = _FakeCache(playlists, feats, artists=artists, neighbours=neighbours)

    res = evaluate_similarity(cache, ks=(1, 2), n_boot=50)
    assert res["model"]["recall@2"] == 0.0
    assert res["beats_popularity"] is False


def test_coverage_is_reported_because_it_is_a_minority_of_the_corpus():
    """A metric over 30% of the corpus must never read as a corpus statement."""
    feats = _corpus(100)
    playlists = {"p1": ["t00", "t01", "t02"]}
    artists = {t: t for t in feats}
    res = evaluate_similarity(_FakeCache(playlists, feats, artists=artists),
                              ks=(1,), n_boot=20)
    assert res["n_analyzed"] == 100
    assert res["n_seeds"] == 3
    assert res["coverage"] == pytest.approx(0.03)


def test_no_usable_pairs_returns_a_stated_zero_not_a_crash():
    assert evaluate_similarity(_FakeCache({}, _corpus(5)))["n_seeds"] == 0


# ── the null model ───────────────────────────────────────────────────────────

def test_null_model_finds_structure_in_genuinely_clustered_data():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-3, 0.3, (40, 5)), rng.normal(3, 0.3, (40, 5))])
    res = cluster_null_model(X, k_range=(2, 3), n_shuffles=8, seed=0)
    assert res["real_silhouette"] > res["null_silhouette_max"]
    assert res["n_null_ge_real"] == 0
    assert res["verdict"].startswith("structure beyond")


def test_null_model_calls_out_structureless_data():
    """THE case this exists for: uniform noise has no groups, so the harness
    must say so rather than dutifully reporting whatever k KMeans picked."""
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, (120, 5))           # one blob, no structure
    res = cluster_null_model(X, k_range=(2, 3), n_shuffles=8, seed=1)
    assert res["n_null_ge_real"] > 0, (
        "shuffled noise should score as well as unshuffled noise")
    assert res["verdict"] == "structure indistinguishable from noise"


def test_the_p_value_floor_is_reported_rather_than_hidden():
    """At n=8 the smallest achievable p is 1/9 = 0.111, which looks like a
    non-result and is actually the strongest available. The flag says which."""
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-3, 0.3, (40, 5)), rng.normal(3, 0.3, (40, 5))])
    res = cluster_null_model(X, k_range=(2, 2), n_shuffles=8, seed=0)
    assert res["p_at_floor"] is True
    assert res["p_value"] == res["p_floor"]


# ── the stratified view that reversed the headline ──────────────────────────

def test_stratification_separates_the_two_regimes():
    """The aggregate said 'acoustic loses to popularity'. Stratifying by how
    famous a seed's co-members are showed acoustic winning 7x where they are
    obscure and losing where they are famous — because the ground truth is
    popularity-biased, not because the features are useless.

    This fixture reproduces that shape in miniature: an obscure playlist the
    acoustic ranker gets right, and a famous one it gets wrong.
    """
    from .model_eval import stratified_by_popularity

    feats = _corpus(12)
    popularity = {f"t{i:02d}": (90 if i >= 8 else 5) for i in range(12)}
    artists = {t: t for t in feats}
    playlists = {
        "obscure": ["t00", "t01", "t02"],     # all unpopular
        "famous": ["t08", "t09", "t10"],      # all popular
    }
    neighbours = {
        # acoustic nails the obscure playlist...
        "t00": ["t01", "t02"], "t01": ["t00", "t02"], "t02": ["t00", "t01"],
        # ...and misses the famous one entirely
        "t08": ["t00", "t01"], "t09": ["t00", "t01"], "t10": ["t00", "t01"],
    }
    cache = _FakeCache(playlists, feats, artists=artists, popularity=popularity,
                       neighbours=neighbours)

    res = stratified_by_popularity(cache, k=2, cut=50, n_boot=50)
    assert res["strata"]["unpopular"]["winner"] == "acoustic"
    assert res["strata"]["unpopular"]["n_seeds"] == 3
    assert res["strata"]["popular"]["winner"] == "popularity"


def test_stratification_reports_both_strata_even_when_one_is_small():
    """The unpopular stratum is the interesting one and it is the SMALLER one
    (93 of 588 live). Dropping a stratum for being small would delete the
    finding."""
    from .model_eval import stratified_by_popularity

    feats = _corpus(8)
    popularity = {t: (95 if t >= "t06" else 3) for t in feats}
    artists = {t: t for t in feats}
    playlists = {"a": ["t00", "t01"], "b": ["t06", "t07"]}
    cache = _FakeCache(playlists, feats, artists=artists, popularity=popularity,
                       neighbours={t: [] for t in feats})
    res = stratified_by_popularity(cache, k=2, n_boot=20)
    assert set(res["strata"]) == {"unpopular", "popular"}
