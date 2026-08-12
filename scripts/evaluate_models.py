"""evaluate_models.py — the two numbers the models have never had.

    uv run python scripts/evaluate_models.py                 # both
    uv run python scripts/evaluate_models.py --similarity    # recall@k only
    uv run python scripts/evaluate_models.py --clusters      # null model only
    uv run python scripts/evaluate_models.py --json          # machine-readable

`similar()` and the cluster model both ship to visitors and neither had an
offline evaluation: the tests covered mechanics and latency, not quality. This
prints recall@k against playlist co-occurrence (with a random and a POPULARITY
baseline, which is the one that matters) and a null-model check on the
clustering.

Read the caveats it prints. The ground truth is taste adjacency, not acoustic
similarity, and it covers a minority of the corpus.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.analysis.model_eval import (  # noqa: E402
    cluster_null_model,
    evaluate_similarity,
    playlist_truth,
)
from src.store.cache import FeatureCache  # noqa: E402


def _similarity(cache) -> dict:
    truth = playlist_truth(cache)
    res = evaluate_similarity(cache, truth=truth)
    if not res.get("n_seeds"):
        print("  no usable playlist pairs — import a playlist first")
        return res

    print("\n── recall@k vs playlist co-occurrence " + "─" * 34)
    print(f"  seeds        : {res['n_seeds']} of {res['n_analyzed']} analyzed "
          f"({res['coverage']:.1%} coverage)")
    print(f"  pairs        : {res['n_pairs']:,}")
    print(f"  {'k':>4}  {'model':>8}  {'popularity':>11}  {'random':>8}   95% CI")
    for key in res["model"]:
        k = key.split("@")[1]
        ci = res["ci95"][key]
        print(f"  {k:>4}  {res['model'][key]:>8.4f}  "
              f"{res['baseline_popularity'][key]:>11.4f}  "
              f"{res['baseline_random'][key]:>8.4f}   [{ci[0]:.4f}, {ci[1]:.4f}]")
    verdict = ("BEATS the popularity baseline at every k"
               if res["beats_popularity"] else
               "DOES NOT beat the popularity baseline at every k")
    print(f"\n  → acoustic similarity {verdict}.")
    print("  Caveat: playlist co-occurrence is TASTE adjacency, not acoustic")
    print("  similarity — this is concordance evidence, never validation (D-68).")
    print(f"  It also covers {res['coverage']:.0%} of the corpus, so it is not a")
    print("  statement about the corpus.")
    return res


def _clusters(cache) -> dict:
    from src.store import clusters as cl

    model = cl.latest_model(cache, "song")
    if model is None:
        print("  no promoted cluster model")
        return {}
    import numpy as np

    feats = cl._drop_twins(cl._drop_broken(cache.all_features()),
                           cache.excluded_from_aggregates())
    cols = list(model.feature_cols)
    ids = [t for t, f in feats.items()
           if all(isinstance(f.get(c), (int, float)) for c in cols)]
    X = np.array([[float(feats[t][c]) for c in cols] for t in ids])
    mean = np.array(model.scaler_mean, dtype=float)
    std = np.where(np.array(model.scaler_std, dtype=float) == 0, 1.0,
                   np.array(model.scaler_std, dtype=float))
    Xs = (X - mean) / std

    print(f"\n── is the clustering real? (null model, n={len(ids)}) " + "─" * 20)
    res = cluster_null_model(Xs)
    print(f"  served model : {model.id} (k={model.k})")
    print(f"  real         : k={res['real_k']}  silhouette={res['real_silhouette']}")
    print(f"  shuffled     : mean {res['null_silhouette_mean']} "
          f"max {res['null_silhouette_max']}  (k chosen: {res['null_ks']})")
    floor = (" (the FLOOR at this shuffle count — no shuffle came close)"
             if res.get("p_at_floor") else "")
    print(f"  beat by      : {res['n_null_ge_real']} of {res['n_shuffles']} shuffles")
    print(f"  p-value      : {res['p_value']}{floor}   z={res['z_score']}")
    print(f"\n  → {res['verdict']}.")
    if res["n_null_ge_real"] > 0:
        print("  The groups the site shows are what KMeans imposes on ANY cloud")
        print("  of this shape — not a fact about the music. Say so on the page.")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--similarity", action="store_true")
    ap.add_argument("--clusters", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    both = not (args.similarity or args.clusters)

    cache = FeatureCache()
    out: dict = {}
    if both or args.similarity:
        out["similarity"] = _similarity(cache)
    if both or args.clusters:
        out["clusters"] = _clusters(cache)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
