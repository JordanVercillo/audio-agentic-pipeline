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
    """The whole point: correlated directions must stop voting twice.

    The claim is DECORRELATION — off-diagonal covariance goes to ~0. It is
    deliberately not "the covariance is exactly the identity": the shipped
    transform adds shrinkage (`cov + lambda*I`) to keep a near-collinear corpus
    from amplifying noise, and that biases the diagonal by O(lambda). Asserting
    exact identity here would fail for the guard that makes the transform safe,
    which is the wrong thing to protect.
    """
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, (500, 1))
    X = np.hstack([base, base * 0.98 + rng.normal(0, 0.05, (500, 1)),  # near-duplicates
                   rng.normal(0, 1, (500, 1))])

    corr_before = abs(np.corrcoef(_zscore(X), rowvar=False)[0, 1])
    assert corr_before > 0.9, "fixture no longer has correlated columns"

    W = _whiten(X)
    corr_after = np.corrcoef(W, rowvar=False)
    off = corr_after[~np.eye(corr_after.shape[0], dtype=bool)]
    assert np.abs(off).max() < 1e-6, (
        f"whitening left correlation behind: max |off-diagonal| = {np.abs(off).max()}")
    # THE SAFETY PROPERTY, and it is not "every axis has variance 1".
    #
    # This fixture contains two near-duplicate columns, so one principal
    # direction carries almost no real variance. Naive whitening divides by the
    # square root of that near-zero eigenvalue and AMPLIFIES it into the
    # dominant term — ranking by numerical noise. Shrinkage inflates the
    # eigenvalue instead, so that direction comes out DAMPED (measured ~0.53
    # here) rather than blown up.
    #
    # So the assertion is one-sided: nothing may exceed unit variance. A
    # two-sided "all axes ~1.0" assertion would fail precisely for the guard
    # that makes the transform safe.
    var = W.var(axis=0)
    assert var.max() < 1.01, f"an axis was amplified past unit variance: {var}"
    assert var.min() < 0.9, (
        "the near-collinear direction was NOT damped - shrinkage is not doing "
        f"its job: {var}")
    # the two well-supported directions still carry full weight
    assert sorted(var)[-2] > 0.99, var


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


def test_paired_comparison_reports_no_difference_for_identical_sets():
    """The control: comparing a set against ITSELF must never claim a winner.
    A harness that finds a difference here would find one anywhere."""
    from .metric_experiment import paired_feature_sets

    class _C:
        def __init__(self):
            self.f = {f"t{i:03d}": {"a": float(i), "b": float(i % 7),
                                    "c": float((i * 13) % 11)} for i in range(200)}
            self.pl = {f"p{j}": [f"t{(j * 7 + i) % 200:03d}" for i in range(6)]
                       for j in range(12)}

        def all_features(self):
            return self.f

        def excluded_from_aggregates(self):
            return set()

        def playlist_track_ids(self):
            return self.pl

        def library_rows(self):
            return [{"id": t, "primary_artist_id": t, "artist": t,
                     "popularity": 10} for t in self.f]

    res = paired_feature_sets(_C(), ["a", "b", "c"], ["a", "b", "c"], n_splits=8)
    assert res["overall"]["mean_delta"] == 0.0
    assert res["overall"]["significant"] is False
    assert res["overall"]["verdict"] == "no difference detected"


def test_the_outer_holdout_never_overlaps_the_selection_pool():
    """The load-bearing property of nested selection.

    If one playlist appeared in both, the "untouched" holdout would be scoring
    evidence the selection already used, and the whole point — catching a
    selection that only looks good on its own data — would silently vanish.
    Measured live 2026-08-12, that catch was worth having: greedy elimination
    gained +14% on the pool and lost 11.3% on the holdout.
    """
    from .metric_experiment import nested_feature_selection

    class _C:
        def __init__(self):
            rng = __import__("random").Random(0)
            self.f = {f"t{i:03d}": {c: rng.random() for c in ("a", "b", "c", "d")}
                      for i in range(400)}
            keys = sorted(self.f)
            self.pl = {f"p{j:02d}": [keys[(j * 11 + i) % 400] for i in range(8)]
                       for j in range(24)}

        def all_features(self):
            return self.f

        def excluded_from_aggregates(self):
            return set()

        def playlist_track_ids(self):
            return self.pl

        def library_rows(self):
            return [{"id": t, "primary_artist_id": t, "artist": t, "popularity": 10}
                    for t in self.f]

    c = _C()
    res = nested_feature_selection(c, ["a", "b", "c", "d"], n_splits=4)
    assert res["n_pool_playlists"] + res["n_holdout_playlists"] == len(c.pl), (
        "playlists went missing between the two partitions")
    assert res["n_holdout_playlists"] >= 1 and res["n_pool_playlists"] >= 1
    # the holdout is scored, and it is scored on the SELECTED set
    assert res["holdout_base"] is not None
    assert res["holdout_selected"] is not None
    assert set(res["selected_cols"]) <= {"a", "b", "c", "d"}
    assert not (set(res["dropped"]) & set(res["selected_cols"]))


def test_selection_never_drops_below_a_floor_of_columns():
    """A greedy loop that keeps finding 'improvements' in noise would strip the
    set to one column. The floor stops that from being expressible."""
    from .metric_experiment import nested_feature_selection

    class _C:
        def __init__(self):
            rng = __import__("random").Random(1)
            self.f = {f"t{i:03d}": {c: rng.random() for c in ("a", "b", "c", "d", "e")}
                      for i in range(300)}
            keys = sorted(self.f)
            self.pl = {f"p{j:02d}": [keys[(j * 7 + i) % 300] for i in range(6)]
                       for j in range(18)}

        def all_features(self):
            return self.f

        def excluded_from_aggregates(self):
            return set()

        def playlist_track_ids(self):
            return self.pl

        def library_rows(self):
            return [{"id": t, "primary_artist_id": t, "artist": t, "popularity": 10}
                    for t in self.f]

    res = nested_feature_selection(_C(), ["a", "b", "c", "d", "e"], n_splits=4)
    assert len(res["selected_cols"]) >= 3
