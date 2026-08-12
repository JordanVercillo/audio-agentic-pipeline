"""Can a better distance metric beat the shipped one? Measured, held out.

The shipped `similar()` z-scores 13 hand-picked columns and takes Euclidean
distance. Two known weaknesses, both structural rather than accidental:

  1. **The columns were chosen by judgement**, not by any selection procedure.
  2. **Euclidean distance over correlated features double-counts.** Five of the
     thirteen are MFCC means, which correlate with the spectral centroid and
     rolloff columns — so "timbre" gets roughly half the vote purely because
     more columns happen to describe it. Nobody decided that.

Whitening fixes (2) with no hyperparameter and no new data: rotate into the
principal axes and scale each to unit variance, so correlated directions stop
voting twice. That is Mahalanobis distance in the original space.

## The discipline this file exists to enforce

Comparing metrics on the same pairs used to pick the winner is how you
manufacture an improvement. Every number below is computed on **held-out
playlists**:

  - the split is by PLAYLIST, not by seed track. Splitting by seed leaks — the
    same playlist's members would land on both sides, so the test pairs would
    share structure with the training pairs.
  - candidate metrics are chosen on the train half, reported on the test half.
  - the shipped metric is re-measured on the same test half, so the comparison
    is like-for-like rather than against the number in an old report.

Nothing here changes production. It answers "would it be better?" — shipping is
a separate, deliberate step, and only if the held-out number says yes.
"""
from __future__ import annotations

import random
from typing import Any, Callable, Optional

import numpy as np

from .model_eval import DEFAULT_KS, MAX_CURATED_PLAYLIST, _bootstrap_ci, _recall


def build_matrix(cache: Any, cols: list[str]) -> tuple[list[str], np.ndarray]:
    """(ids, X) over tracks with every column present, in the serving pool.

    Uses the SAME exclusions as `similar()` — twins and source-unvalidated
    tracks sit out — or the comparison would be against a different candidate
    pool than production uses.
    """
    feats = cache.all_features()
    excluded = cache.excluded_from_aggregates()
    ids, rows = [], []
    for tid in sorted(feats):
        if tid in excluded:
            continue
        f = feats[tid]
        vals = [f.get(c) for c in cols]
        if any(v is None or not isinstance(v, (int, float)) for v in vals):
            continue
        ids.append(tid)
        rows.append([float(v) for v in vals])
    return ids, np.asarray(rows, dtype=float)


# ── the candidate transforms ────────────────────────────────────────────────

def _zscore(X: np.ndarray) -> np.ndarray:
    """What ships today: centre and scale each column independently."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    return (X - mu) / sd


def _whiten(X: np.ndarray, n_components: Optional[int] = None) -> np.ndarray:
    """PCA whitening — the SAME transform production serves.

    Delegates to `src.store.metric.whitening_matrix` so the measured number and
    the shipped behaviour cannot drift apart. `n_components` truncates
    afterwards, for the reduced-dimension variants this file also scores.
    """
    from ..store.metric import whitening_matrix

    Z = _zscore(X)
    W = whitening_matrix(Z)
    if W is None:
        return Z                        # too small to whiten; production agrees
    Y = Z @ np.asarray(W, dtype=float)
    if n_components:
        # Order by how much the corpus varies along each whitened axis.
        keep = np.argsort(Y.var(axis=0))[::-1][:n_components]
        Y = Y[:, keep]
    return Y


TRANSFORMS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "shipped (z-score + euclidean)": _zscore,
    "whitened (mahalanobis)": _whiten,
    "whitened, top 8 components": lambda X: _whiten(X, n_components=8),
    "whitened, top 5 components": lambda X: _whiten(X, n_components=5),
}


def knn(ids: list[str], Y: np.ndarray, seed_id: str, k: int) -> list[str]:
    """The k nearest ids to `seed_id`, itself excluded. Exact, no index."""
    try:
        i = ids.index(seed_id)
    except ValueError:
        return []
    d = np.linalg.norm(Y - Y[i], axis=1)
    d[i] = np.inf
    return [ids[j] for j in np.argsort(d)[:k]]


# ── the held-out comparison ─────────────────────────────────────────────────

def split_playlists(cache: Any, *, seed: int = 0, test_frac: float = 0.5,
                    max_playlist: int = MAX_CURATED_PLAYLIST
                    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Partition CURATED playlists into (train, test).

    By playlist, never by track: two members of one playlist are the same piece
    of evidence, so putting one in train and one in test leaks it across the
    split and every candidate looks better than it is.
    """
    pl = {p: t for p, t in cache.playlist_track_ids().items()
          if 2 <= len(set(t)) <= max_playlist}
    keys = sorted(pl)
    random.Random(seed).shuffle(keys)
    cut = int(len(keys) * (1 - test_frac))
    return ({k: pl[k] for k in keys[:cut]}, {k: pl[k] for k in keys[cut:]})


def _truth_from(playlists: dict[str, list[str]], analyzed: set[str],
                artist_of: dict[str, str], *,
                exclude_same_artist: bool = True) -> dict[str, set[str]]:
    truth: dict[str, set[str]] = {}
    for members in playlists.values():
        uniq = sorted({t for t in members if t in analyzed})
        for a in uniq:
            for b in uniq:
                if a == b:
                    continue
                if exclude_same_artist and artist_of.get(a) and \
                        artist_of.get(a) == artist_of.get(b):
                    continue
                truth.setdefault(a, set()).add(b)
    return truth


def compare_metrics(cache: Any, cols: list[str], *, ks: tuple[int, ...] = DEFAULT_KS,
                    seed: int = 0, n_boot: int = 300) -> dict[str, Any]:
    """Score every candidate transform on held-out playlists."""
    ids, X = build_matrix(cache, cols)
    analyzed = set(ids)
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}

    train_pl, test_pl = split_playlists(cache, seed=seed)
    train = _truth_from(train_pl, analyzed, artist_of)
    test = _truth_from(test_pl, analyzed, artist_of)

    kmax = max(ks)
    out: dict[str, Any] = {
        "n_tracks": len(ids), "n_features": len(cols),
        "n_train_playlists": len(train_pl), "n_test_playlists": len(test_pl),
        "n_train_seeds": len(train), "n_test_seeds": len(test),
        "results": {},
    }
    for name, fn in TRANSFORMS.items():
        Y = fn(X)
        scores: dict[str, Any] = {}
        for split_name, truth in (("train", train), ("test", test)):
            per_k: dict[int, list[float]] = {k: [] for k in ks}
            for s, relevant in sorted(truth.items()):
                ranked = knn(ids, Y, s, kmax)
                for k in ks:
                    per_k[k].append(_recall(ranked, relevant, k))
            scores[split_name] = {
                f"recall@{k}": round(sum(v) / len(v), 4) if v else 0.0
                for k, v in per_k.items()}
            if split_name == "test":
                scores["test_ci95"] = {
                    f"recall@{k}": _bootstrap_ci(v, n=n_boot, seed=seed)
                    for k, v in per_k.items()}
        out["results"][name] = scores
    return out


def repeated_comparison(cache: Any, cols: list[str], *, k: int = 10,
                        n_splits: int = 20, baseline: str = "shipped (z-score + euclidean)",
                        challenger: str = "whitened (mahalanobis)") -> dict[str, Any]:
    """Does the challenger beat the baseline CONSISTENTLY, or did one split flatter it?

    A single held-out split gave whitening +18% at k=10 while making it slightly
    WORSE on the train half — and with overlapping confidence intervals. An
    effect that appears only in the half you report is what noise looks like.

    So: re-split many times and pair the two metrics on each split. Paired is
    the point — both metrics see the identical test seeds every round, so the
    split-to-split variance (which is large here, and is about WHICH playlists
    landed in test) cancels instead of drowning the comparison.
    """
    ids, X = build_matrix(cache, cols)
    analyzed = set(ids)
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}
    Y_base = TRANSFORMS[baseline](X)
    Y_chal = TRANSFORMS[challenger](X)

    deltas, base_scores, chal_scores = [], [], []
    for s in range(n_splits):
        _, test_pl = split_playlists(cache, seed=s)
        truth = _truth_from(test_pl, analyzed, artist_of)
        if not truth:
            continue
        b, c = [], []
        for seed_id, relevant in sorted(truth.items()):
            b.append(_recall(knn(ids, Y_base, seed_id, k), relevant, k))
            c.append(_recall(knn(ids, Y_chal, seed_id, k), relevant, k))
        mb, mc = sum(b) / len(b), sum(c) / len(c)
        base_scores.append(mb)
        chal_scores.append(mc)
        deltas.append(mc - mb)

    n = len(deltas)
    mean_d = sum(deltas) / n
    sd = (sum((d - mean_d) ** 2 for d in deltas) / (n - 1)) ** 0.5 if n > 1 else 0.0
    se = sd / (n ** 0.5) if n else 0.0
    return {
        "k": k, "n_splits": n,
        "baseline": baseline, "challenger": challenger,
        "baseline_mean": round(sum(base_scores) / n, 4),
        "challenger_mean": round(sum(chal_scores) / n, 4),
        "mean_delta": round(mean_d, 4),
        "delta_ci95": (round(mean_d - 1.96 * se, 4), round(mean_d + 1.96 * se, 4)),
        "challenger_wins": sum(1 for d in deltas if d > 0),
        # The splits share a corpus, so these are not independent samples and
        # this is a descriptive interval, not a hypothesis test.
        "consistent": sum(1 for d in deltas if d > 0) >= 0.8 * n
                      and (mean_d - 1.96 * se) > 0,
    }
