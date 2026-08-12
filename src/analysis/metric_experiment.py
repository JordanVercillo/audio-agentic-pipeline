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


# ── candidate FEATURE SETS (slice 2 of the ML track) ────────────────────────
# Each is a HYPOTHESIS, not a search result. Greedy selection over 83 columns
# would be ~800 evaluations against ~300 seeds: it would find noise and call it
# a finding, and the winner would not survive a re-split. Six named sets keep
# the multiple-comparisons burden small enough that a win means something.

def feature_sets(all_cols: list[str], shipped: list[str]) -> dict[str, list[str]]:
    """Named candidate column sets, built from what the corpus actually has."""
    have = set(all_cols)

    def take(pred) -> list[str]:
        return sorted(c for c in all_cols if pred(c))

    mfcc_mean = take(lambda c: c.startswith("mfcc_mean_"))
    contrast = take(lambda c: c.startswith("spectral_contrast_mean_"))
    chroma = take(lambda c: c.startswith("chroma_mean_"))
    # The shipped set minus its five MFCCs — the "timbre out-votes tempo"
    # hypothesis says removing them should help, or at least not hurt.
    shipped_no_mfcc = [c for c in shipped if not c.startswith("mfcc_")]
    core = [c for c in ("tempo_bpm", "rms_mean", "rms_std", "zcr_mean",
                        "spectral_centroid_mean", "spectral_rolloff_mean",
                        "spectral_bandwidth_mean", "spectral_flatness_mean",
                        "harmonic_ratio", "onset_strength_mean",
                        "onset_strength_std", "beats_per_sec")
            if c in have]

    sets = {
        "shipped 13": [c for c in shipped if c in have],
        "shipped minus MFCCs (8)": shipped_no_mfcc,
        "perceptual core (12)": core,
        "core + all 13 MFCC means": core + mfcc_mean,
        "core + spectral contrast": core + contrast,
        "core + MFCC + contrast + chroma": core + mfcc_mean + contrast + chroma,
        "everything numeric": sorted(have),
    }
    return {k: v for k, v in sets.items() if len(v) >= 2}


def compare_feature_sets(cache: Any, sets: dict[str, list[str]], *, k: int = 10,
                         n_splits: int = 10, seed_offset: int = 0,
                         stratify_cut: int = 50) -> dict[str, Any]:
    """Score each candidate set on held-out playlists, overall and stratified.

    Every set sees the IDENTICAL splits, so the comparison is paired and the
    large split-to-split variance cancels. The stratified column is the one
    that matters: the obscure-co-member seeds are where acoustic features earn
    their keep, and the overall average is dominated by the famous ones.
    """
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}
    pop_of = {r["id"]: (r.get("popularity") or 0) for r in rows}

    def _median(xs):
        xs = sorted(xs)
        n = len(xs)
        return 0.0 if not n else (xs[n // 2] if n % 2
                                  else (xs[n // 2 - 1] + xs[n // 2]) / 2)

    out: dict[str, Any] = {"k": k, "n_splits": n_splits, "results": {}}
    prepared = {}
    for name, cols in sets.items():
        ids, X = build_matrix(cache, cols)
        prepared[name] = (ids, set(ids), _whiten(X), cols)

    for name, (ids, idset, Y, cols) in prepared.items():
        overall, obscure, famous = [], [], []
        for s in range(n_splits):
            _, test_pl = split_playlists(cache, seed=seed_offset + s)
            truth = _truth_from(test_pl, idset, artist_of)
            if not truth:
                continue
            o, ob, fa = [], [], []
            for seed_id, relevant in sorted(truth.items()):
                r = _recall(knn(ids, Y, seed_id, k), relevant, k)
                o.append(r)
                (ob if _median([pop_of.get(b, 0) for b in relevant]) < stratify_cut
                 else fa).append(r)
            if o:
                overall.append(sum(o) / len(o))
            if ob:
                obscure.append(sum(ob) / len(ob))
            if fa:
                famous.append(sum(fa) / len(fa))
        out["results"][name] = {
            "n_features": len(cols),
            "overall": round(sum(overall) / len(overall), 4) if overall else None,
            "obscure_costars": round(sum(obscure) / len(obscure), 4) if obscure else None,
            "famous_costars": round(sum(famous) / len(famous), 4) if famous else None,
        }
    return out


def paired_feature_sets(cache: Any, cols_a: list[str], cols_b: list[str], *,
                        k: int = 10, n_splits: int = 40, stratify_cut: int = 50,
                        label_a: str = "A", label_b: str = "B") -> dict[str, Any]:
    """Is set B better than set A? Paired over many splits, with a CI.

    THE reason this exists. A 10-split run said dropping the five MFCCs from the
    shipped set improved the obscure-co-star stratum by ~20% (0.0291 -> 0.0350).
    Re-run paired over 40 splits it was **delta -0.0002, CI (-0.0053, +0.0048),
    winning 23 of 40** — noise, from a stratum with only ~93 seeds. The same
    change was significantly WORSE overall.

    A point estimate from a handful of splits will happily invent a 20%
    improvement here. Anything proposing a feature-set change has to come
    through this function.
    """
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}
    pop_of = {r["id"]: (r.get("popularity") or 0) for r in rows}

    def _median(xs):
        xs = sorted(xs)
        n = len(xs)
        return 0.0 if not n else (xs[n // 2] if n % 2
                                  else (xs[n // 2 - 1] + xs[n // 2]) / 2)

    prep = {}
    for name, cols in ((label_a, cols_a), (label_b, cols_b)):
        ids, X = build_matrix(cache, cols)
        prep[name] = (ids, set(ids), _whiten(X))

    d_overall, d_obscure = [], []
    for s in range(n_splits):
        _, test_pl = split_playlists(cache, seed=s)
        truth = _truth_from(test_pl, prep[label_a][1], artist_of)
        if not truth:
            continue
        scored = {}
        for name, (ids, _idset, Y) in prep.items():
            ov, ob = [], []
            for seed_id, relevant in sorted(truth.items()):
                r = _recall(knn(ids, Y, seed_id, k), relevant, k)
                ov.append(r)
                if _median([pop_of.get(b, 0) for b in relevant]) < stratify_cut:
                    ob.append(r)
            scored[name] = (sum(ov) / len(ov) if ov else None,
                            sum(ob) / len(ob) if ob else None)
        if scored[label_a][0] is not None and scored[label_b][0] is not None:
            d_overall.append(scored[label_b][0] - scored[label_a][0])
        if scored[label_a][1] is not None and scored[label_b][1] is not None:
            d_obscure.append(scored[label_b][1] - scored[label_a][1])

    def _stats(d: list[float]) -> dict[str, Any]:
        n = len(d)
        if n < 2:
            return {"n": n, "verdict": "too few splits"}
        m = sum(d) / n
        sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        se = sd / n ** 0.5
        lo, hi = m - 1.96 * se, m + 1.96 * se
        return {"n": n, "mean_delta": round(m, 4),
                "ci95": (round(lo, 4), round(hi, 4)),
                "b_wins": sum(1 for x in d if x > 0),
                "significant": lo > 0 or hi < 0,
                "verdict": ("B better" if lo > 0 else
                            "A better" if hi < 0 else "no difference detected")}

    return {"k": k, "label_a": label_a, "label_b": label_b,
            "overall": _stats(d_overall), "obscure_costars": _stats(d_obscure)}


def nested_feature_selection(cache: Any, base_cols: list[str], *, k: int = 10,
                             n_splits: int = 30, holdout_frac: float = 0.34,
                             seed: int = 1234) -> dict[str, Any]:
    """Choose columns on one set of playlists, report on playlists never seen.

    WHY THIS AND NOT A PLAIN ABLATION. Scoring 13 single-column drops and
    keeping the winners is selection ON the evaluation data: with 13 tests at
    the usual threshold you expect roughly one false positive by construction,
    and the winner's margin is inflated because you picked the largest of 13
    noisy numbers. Reporting that margin is how a null result gets published as
    a finding.

    So the playlists are cut in three from the start:

        OUTER HOLDOUT (~1/3)  untouched until the very last line
        SELECTION POOL (~2/3) every ablation, every paired split, lives here

    The selection pool is where columns are chosen. The outer holdout is scored
    exactly once, for the final set. Whatever it says is the number — including
    when it disagrees with the selection pool, which is the case worth having
    built this for.
    """
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}

    pl = {p: v for p, v in cache.playlist_track_ids().items()
          if 2 <= len(set(v)) <= MAX_CURATED_PLAYLIST}
    keys = sorted(pl)
    random.Random(seed).shuffle(keys)
    n_hold = max(1, int(len(keys) * holdout_frac))
    holdout_keys, pool_keys = keys[:n_hold], keys[n_hold:]
    holdout = {x: pl[x] for x in holdout_keys}
    pool = {x: pl[x] for x in pool_keys}

    def _score(cols: list[str], playlists: dict[str, list[str]]) -> Optional[float]:
        ids, X = build_matrix(cache, cols)
        Y = _whiten(X)
        truth = _truth_from(playlists, set(ids), artist_of)
        if not truth:
            return None
        vals = [_recall(knn(ids, Y, s, k), rel, k) for s, rel in sorted(truth.items())]
        return sum(vals) / len(vals) if vals else None

    def _pool_delta(cols_a: list[str], cols_b: list[str]) -> dict[str, Any]:
        """Paired over re-splits WITHIN the selection pool only."""
        pa = build_matrix(cache, cols_a)
        pb = build_matrix(cache, cols_b)
        Ya, Yb = _whiten(pa[1]), _whiten(pb[1])
        deltas = []
        pk = sorted(pool)
        for s in range(n_splits):
            rnd = random.Random(s)
            sub = rnd.sample(pk, max(2, len(pk) // 2))
            truth = _truth_from({x: pool[x] for x in sub}, set(pa[0]), artist_of)
            if not truth:
                continue
            a = [_recall(knn(pa[0], Ya, s2, k), rel, k) for s2, rel in sorted(truth.items())]
            b = [_recall(knn(pb[0], Yb, s2, k), rel, k) for s2, rel in sorted(truth.items())]
            if a and b:
                deltas.append(sum(b) / len(b) - sum(a) / len(a))
        n = len(deltas)
        if n < 2:
            return {"n": n, "mean_delta": 0.0, "significant": False}
        m = sum(deltas) / n
        sd = (sum((x - m) ** 2 for x in deltas) / (n - 1)) ** 0.5
        se = sd / n ** 0.5
        lo, hi = m - 1.96 * se, m + 1.96 * se
        return {"n": n, "mean_delta": round(m, 5), "ci95": (round(lo, 5), round(hi, 5)),
                "significant": lo > 0}

    # ── greedy backward elimination, INSIDE the pool ────────────────────────
    current = list(base_cols)
    trail: list[dict[str, Any]] = []
    while len(current) > 3:
        best = None
        for col in current:
            cand = [c for c in current if c != col]
            d = _pool_delta(current, cand)
            if d["significant"] and (best is None or d["mean_delta"] > best[1]["mean_delta"]):
                best = (col, d)
        if best is None:
            break                       # nothing left that helps on the pool
        trail.append({"dropped": best[0], **best[1]})
        current = [c for c in current if c != best[0]]

    # ── the outer holdout, touched once ────────────────────────────────────
    return {
        "k": k,
        "n_holdout_playlists": len(holdout), "n_pool_playlists": len(pool),
        "selected_cols": current, "dropped": [t_["dropped"] for t_ in trail],
        "selection_trail": trail,
        "holdout_base": _score(base_cols, holdout),
        "holdout_selected": _score(current, holdout),
        "pool_base": _score(base_cols, pool),
        "pool_selected": _score(current, pool),
    }
