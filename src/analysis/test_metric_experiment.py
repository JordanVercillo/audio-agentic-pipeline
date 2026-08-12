"""The metric comparison must not be able to manufacture an improvement.

Synthetic only (ground rule 5).
"""
from __future__ import annotations

import numpy as np

from .metric_experiment import (
    _truth_from,
    _whiten,
    _zscore,
    knn,
    split_playlists,
)


class _FakeCache:
    def __init__(self, playlists):
        self._pl = playlists

    def playlist_track_ids(self):
        return self._pl


def test_whitening_actually_decorrelates():
    """The whole point: correlated directions must stop voting twice. After
    whitening the covariance is the identity, so no direction is double-counted."""
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, (500, 1))
    X = np.hstack([base, base * 0.98 + rng.normal(0, 0.05, (500, 1)),  # near-duplicates
                   rng.normal(0, 1, (500, 1))])

    corr_before = abs(np.corrcoef(_zscore(X), rowvar=False)[0, 1])
    assert corr_before > 0.9, "fixture no longer has correlated columns"

    W = _whiten(X)
    cov = np.cov(W, rowvar=False)
    np.testing.assert_allclose(cov, np.eye(cov.shape[0]), atol=1e-6)


def test_whitening_survives_a_degenerate_column():
    """A constant column has zero variance. Without the eps guard its inverse
    square root explodes and that axis dominates every distance."""
    rng = np.random.default_rng(1)
    X = np.hstack([rng.normal(0, 1, (100, 2)), np.zeros((100, 1))])
    W = _whiten(X)
    assert np.isfinite(W).all(), "a zero-variance column produced non-finite output"


def test_a_playlist_is_never_split_across_train_and_test():
    """The leak this guards: two members of one playlist are the SAME piece of
    evidence, so seeing one in train and one in test inflates every candidate."""
    playlists = {f"p{i}": [f"t{i}_{j}" for j in range(5)] for i in range(10)}
    train, test = split_playlists(_FakeCache(playlists), seed=3)
    assert train and test
    assert not (set(train) & set(test)), "a playlist landed in both halves"
    assert set(train) | set(test) == set(playlists)


def test_split_is_deterministic_for_a_seed():
    playlists = {f"p{i}": ["a", "b", "c"] for i in range(8)}
    a, _ = split_playlists(_FakeCache(playlists), seed=7)
    b, _ = split_playlists(_FakeCache(playlists), seed=7)
    assert set(a) == set(b)


def test_knn_never_returns_the_seed_itself():
    ids = [f"t{i}" for i in range(6)]
    Y = np.arange(6, dtype=float).reshape(-1, 1)
    out = knn(ids, Y, "t3", 3)
    assert "t3" not in out
    assert out[0] in ("t2", "t4"), out          # the two adjacent points
    assert knn(ids, Y, "missing", 3) == []


def test_truth_drops_same_artist_pairs_here_too():
    """The comparison harness must apply the SAME leakage rule as the main one,
    or the two sets of numbers are not comparable."""
    playlists = {"p": ["a", "b", "c"]}
    analyzed = {"a", "b", "c"}
    artist = {"a": "X", "b": "X", "c": "Y"}
    truth = _truth_from(playlists, analyzed, artist)
    assert truth["a"] == {"c"}, truth
    assert _truth_from(playlists, analyzed, artist,
                       exclude_same_artist=False)["a"] == {"b", "c"}


def test_unanalyzed_members_do_not_enter_the_truth():
    truth = _truth_from({"p": ["a", "b", "ghost"]}, {"a", "b"}, {"a": "X", "b": "Y"})
    assert "ghost" not in truth.get("a", set())
