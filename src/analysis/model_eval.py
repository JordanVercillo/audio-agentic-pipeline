"""Offline evaluation for the two unsupervised models that ship to visitors.

Until 2026-08-12 neither had one. `similar()` had tests for its MECHANICS (ranks
by distance, excludes itself, bounded latency) and none for its QUALITY, and the
clustering shipped a k and a silhouette with nothing to compare them against.
"Are these songs actually similar?" and "is k=2 real?" were simply unanswered
while both were live on a public site.

This module answers both, on data the project already has. Two deliberate
design choices, because a retrieval number without them is decoration:

**Leakage control.** Two tracks by the same artist are trivially close in
acoustic space, and a human putting them in one playlist is not independent
evidence. Left in, the harness would mostly measure "can we detect the same
artist" and report a flattering number. Same-artist pairs are excluded from the
ground truth by default.

**Baselines.** A recall@k with nothing to beat is unfalsifiable. Every run
reports the same metric for a random ranker and a popularity ranker. Popularity
is the one that matters: if acoustic similarity cannot beat "recommend whatever
is famous", the acoustic part is not earning its place.

**What the ground truth is, and is not.** Playlist co-occurrence measures TASTE
ADJACENCY — two tracks a human chose to sit together. That is not the same
claim as acoustic similarity; playlists deliberately mix sounds. So a result
here is EVIDENCE about the retrieval model, never proof, and the D-68 claim
discipline applies: say "concordance with playlist co-occurrence", never
"validated".

Coverage is reported alongside every number, because the evaluable subset is a
minority of the corpus (measured 2026-08-12: 590 of 1,946 analyzed tracks touch
a usable pair) and a metric over 30% of the corpus must never be read as a
statement about the corpus.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Optional

# A playlist bigger than this is a library dump, not a curation. The live data
# has one 876-track playlist whose co-occurrence signal is "Jordan saved it",
# which is not the taste-adjacency claim this harness rests on.
MAX_CURATED_PLAYLIST = 200

# Two tracks are usable evidence only if a human placed BOTH in one playlist
# and neither is the trivial same-artist case.
DEFAULT_KS = (1, 5, 10, 20)


def playlist_truth(cache: Any, *, max_playlist: int = MAX_CURATED_PLAYLIST,
                   exclude_same_artist: bool = True,
                   analyzed: Optional[set[str]] = None) -> dict[str, set[str]]:
    """seed track -> the set of analyzed tracks a human shelved beside it.

    Only tracks WE have features for can appear on either side: an unanalyzed
    co-member is not retrievable, so counting it would depress recall for a
    reason that has nothing to do with the model.
    """
    analyzed = analyzed if analyzed is not None else set(cache.all_features())
    rows = cache.library_rows()
    artist_of = {r["id"]: (r.get("primary_artist_id")
                           or (r.get("artist") or "").split(",")[0].strip().lower())
                 for r in rows}

    by_playlist: dict[str, list[str]] = {
        pl: [t for t in tids if t in analyzed]
        for pl, tids in cache.playlist_track_ids().items()}

    truth: dict[str, set[str]] = defaultdict(set)
    for members in by_playlist.values():
        if not (2 <= len(members) <= max_playlist):
            continue
        uniq = sorted(set(members))
        for a in uniq:
            for b in uniq:
                if a == b:
                    continue
                if exclude_same_artist and artist_of.get(a) and \
                        artist_of.get(a) == artist_of.get(b):
                    continue          # trivially close; not independent evidence
                truth[a].add(b)
    return {k: v for k, v in truth.items() if v}


def _recall(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the reachable relevant items found in the top k.

    Denominator is min(k, |relevant|), not |relevant|: with 40 co-members and
    k=10 the best possible score must be 1.0, or the metric punishes the model
    for a ceiling the metric itself imposed.
    """
    if not relevant or k <= 0:
        return 0.0
    hits = sum(1 for t in ranked[:k] if t in relevant)
    return hits / min(k, len(relevant))


def _bootstrap_ci(values: list[float], *, n: int = 1000, seed: int = 0,
                  alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap over SEEDS — the unit of independence here."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    size = len(values)
    for _ in range(n):
        means.append(sum(rng.choice(values) for _ in range(size)) / size)
    means.sort()
    lo = means[int(alpha / 2 * n)]
    hi = means[min(n - 1, int((1 - alpha / 2) * n))]
    return (round(lo, 4), round(hi, 4))


def evaluate_similarity(cache: Any, *, ks: tuple[int, ...] = DEFAULT_KS,
                        truth: Optional[dict[str, set[str]]] = None,
                        seed: int = 0, n_boot: int = 500) -> dict[str, Any]:
    """recall@k for `similar()` against playlist co-occurrence, vs 2 baselines.

    Returns the model's numbers, a random baseline, a popularity baseline, and
    the coverage the whole thing rests on.
    """
    analyzed = set(cache.all_features())
    truth = truth if truth is not None else playlist_truth(cache, analyzed=analyzed)
    if not truth:
        return {"n_seeds": 0, "note": "no usable playlist pairs"}

    rows = cache.library_rows()
    pop_of = {r["id"]: (r.get("popularity") or 0) for r in rows}
    # Candidate universe = what `similar()` could return: analyzed, minus the
    # tracks the serving layer withholds. Baselines must draw from the SAME
    # pool or they are not comparable.
    excluded = cache.excluded_from_aggregates()
    universe = sorted(analyzed - set(excluded))
    by_pop = sorted(universe, key=lambda t: (-pop_of.get(t, 0), t))

    kmax = max(ks)
    rng = random.Random(seed)
    per_k: dict[int, list[float]] = {k: [] for k in ks}
    per_k_rand: dict[int, list[float]] = {k: [] for k in ks}
    per_k_pop: dict[int, list[float]] = {k: [] for k in ks}

    for s, relevant in sorted(truth.items()):
        ranked = [t for t, _ in cache.similar(s, k=kmax)]
        rand = rng.sample([t for t in universe if t != s],
                          min(kmax, max(0, len(universe) - 1)))
        pop = [t for t in by_pop if t != s][:kmax]
        for k in ks:
            per_k[k].append(_recall(ranked, relevant, k))
            per_k_rand[k].append(_recall(rand, relevant, k))
            per_k_pop[k].append(_recall(pop, relevant, k))

    def _summary(store: dict[int, list[float]]) -> dict[str, Any]:
        return {f"recall@{k}": round(sum(v) / len(v), 4) for k, v in store.items()}

    n_seeds = len(truth)
    return {
        "n_seeds": n_seeds,
        "n_analyzed": len(analyzed),
        "coverage": round(n_seeds / len(analyzed), 4) if analyzed else 0.0,
        "n_pairs": sum(len(v) for v in truth.values()) // 2,
        "model": _summary(per_k),
        "baseline_random": _summary(per_k_rand),
        "baseline_popularity": _summary(per_k_pop),
        "ci95": {f"recall@{k}": _bootstrap_ci(v, n=n_boot, seed=seed)
                 for k, v in per_k.items()},
        "beats_popularity": all(
            (sum(per_k[k]) / len(per_k[k])) > (sum(per_k_pop[k]) / len(per_k_pop[k]))
            for k in ks),
    }


# ── is the clustering real, or did KMeans just cut the cloud in half? ────────

def cluster_null_model(X, *, k_range: tuple[int, int] = (2, 6),
                       n_shuffles: int = 20, seed: int = 0) -> dict[str, Any]:
    """Compare the real silhouette against column-shuffled data.

    Shuffling each column independently destroys the JOINT structure (which
    tracks go together) while preserving every column's own distribution. So a
    clustering that scores no better on real data than on shuffled data has
    found nothing about the music: it has found the shape KMeans imposes on any
    cloud of that size.

    This is the test the live k=2 model has never faced. Measured 2026-08-12 it
    serves at silhouette 0.148 with a 937/957 split, which is what a bisected
    blob looks like.
    """
    import numpy as np

    from .clustering import cluster_tracks

    X = np.asarray(X, dtype=float)
    _, real_k, real_sil = cluster_tracks(X, k_range=k_range, random_state=seed)

    rng = np.random.default_rng(seed)
    null_sils, null_ks = [], []
    for _ in range(n_shuffles):
        shuffled = X.copy()
        for j in range(shuffled.shape[1]):
            rng.shuffle(shuffled[:, j])          # break the joint, keep marginals
        _, nk, ns = cluster_tracks(shuffled, k_range=k_range, random_state=seed)
        null_sils.append(float(ns))
        null_ks.append(int(nk))

    mean_null = sum(null_sils) / len(null_sils)
    sd = math.sqrt(sum((s - mean_null) ** 2 for s in null_sils) / len(null_sils)) \
        if len(null_sils) > 1 else 0.0
    # How many shuffles matched or beat the real score? A high count means the
    # real structure is indistinguishable from noise.
    n_ge = sum(1 for s in null_sils if s >= real_sil)
    return {
        "real_k": int(real_k),
        "real_silhouette": round(float(real_sil), 4),
        "null_silhouette_mean": round(mean_null, 4),
        "null_silhouette_max": round(max(null_sils), 4),
        "null_ks": sorted(set(null_ks)),
        "n_shuffles": n_shuffles,
        "n_null_ge_real": n_ge,
        # Empirical p: P(a noise dataset scores this well). The +1s are the
        # standard small-sample correction, which also FLOORS p at
        # 1/(n_shuffles+1) — at n=20 the best achievable p is 0.0476, which
        # reads like a borderline result and is actually the strongest one
        # available. `p_at_floor` says which it is; the z-score is the
        # informative statistic when it is.
        "p_value": round((n_ge + 1) / (n_shuffles + 1), 4),
        "p_floor": round(1 / (n_shuffles + 1), 4),
        "p_at_floor": n_ge == 0,
        "z_score": round((real_sil - mean_null) / sd, 2) if sd > 0 else None,
        "verdict": ("structure indistinguishable from noise"
                    if n_ge > 0
                    else "structure beyond what KMeans imposes on noise"),
    }


def stratified_by_popularity(cache: Any, *, k: int = 10, cut: int = 50,
                             truth: Optional[dict[str, set[str]]] = None,
                             n_boot: int = 500, seed: int = 0) -> dict[str, Any]:
    """Where does acoustic similarity actually earn its keep?

    The aggregate recall@k says the acoustic model loses to a popularity ranker.
    That aggregate is misleading, and this function is why.

    Playlist co-occurrence is popularity-biased: measured 2026-08-12, the
    co-members in the ground truth have median popularity 68 against the
    corpus's 48. A static "most famous tracks" list therefore scores well on the
    majority of seeds for reasons that have nothing to do with sound — and
    because recall's denominator is min(k, |relevant|), a seed with many
    co-members converts a single lucky hit into a large score.

    Splitting seeds by how famous their co-members are separates the two
    regimes. The unpopular stratum is the one a discovery product exists for:
    if you cannot beat "recommend whatever is famous" THERE, the acoustic
    features are not doing anything a popularity sort could not.
    """
    analyzed = set(cache.all_features())
    truth = truth if truth is not None else playlist_truth(cache, analyzed=analyzed)
    rows = cache.library_rows()
    pop_of = {r["id"]: (r.get("popularity") or 0) for r in rows}
    excluded = set(cache.excluded_from_aggregates())
    universe = sorted(analyzed - excluded)
    by_pop = sorted(universe, key=lambda t: (-pop_of.get(t, 0), t))

    def _median(xs: list[float]) -> float:
        xs = sorted(xs)
        n = len(xs)
        if not n:
            return 0.0
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    buckets: dict[str, dict[str, list[float]]] = {
        "unpopular": {"model": [], "popularity": []},
        "popular": {"model": [], "popularity": []},
    }
    for s, relevant in sorted(truth.items()):
        med = _median([pop_of.get(b, 0) for b in relevant])
        key = "unpopular" if med < cut else "popular"
        ranked = [t for t, _ in cache.similar(s, k=k)]
        popranked = [t for t in by_pop if t != s][:k]
        buckets[key]["model"].append(_recall(ranked, relevant, k))
        buckets[key]["popularity"].append(_recall(popranked, relevant, k))

    out: dict[str, Any] = {"k": k, "popularity_cut": cut, "strata": {}}
    for key, b in buckets.items():
        if not b["model"]:
            continue
        m = sum(b["model"]) / len(b["model"])
        p = sum(b["popularity"]) / len(b["popularity"])
        out["strata"][key] = {
            "n_seeds": len(b["model"]),
            "model": round(m, 4),
            "popularity": round(p, 4),
            "model_ci95": _bootstrap_ci(b["model"], n=n_boot, seed=seed),
            "popularity_ci95": _bootstrap_ci(b["popularity"], n=n_boot, seed=seed),
            "ratio": round(m / p, 2) if p > 0 else None,
            "winner": "acoustic" if m > p else "popularity",
        }
    return out
