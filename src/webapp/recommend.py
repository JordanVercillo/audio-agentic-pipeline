"""
recommend.py — the recommendation explorer engine (Epic G).

Rebuilds Spotify's retired /recommendations as a TRANSPARENT engine over our
own perceptual features (VISION_SPECS: the thesis capstone — the rebuilt
features are good enough to power retrieval):

    - min_<col> / max_<col>   hard filters (prune, like the API's tunables)
    - target_<col>            rank by closeness (z-normalized against the
                              corpus via feature_stats — the same honesty
                              baseline /explore uses)
    - seed track              fills the targets VISIBLY from that track's own
                              values ("more like this", explainable — every
                              target sits in the form, no hidden model)

`popularity` joins as a constraint axis (fetched context — filtering and
ranking by it is display/analysis use, never model training). Deterministic:
same cache + same constraints → same ranking (score, then name, then id).
Pure functions — the route wires the cache in; tests run on dicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

# Kinds mirror the retired API's tunable prefixes.
KINDS = ("min", "max", "target")
POPULARITY = "popularity"  # not a perceptual column — merged in by the caller


@dataclass(frozen=True)
class Constraint:
    column: str
    kind: str    # "min" | "max" | "target"
    value: float


def parse_constraints(params: dict[str, str], allowed: set[str]) -> list[Constraint]:
    """min_/max_/target_ query params → Constraints, whitelisted + numeric.

    Unknown columns and non-numeric values are silently ignored (a hand-edited
    URL degrades to fewer constraints, never to an error page).
    """
    out: list[Constraint] = []
    for name, raw in params.items():
        for kind in KINDS:
            prefix = f"{kind}_"
            if name.startswith(prefix):
                col = name[len(prefix):]
                if col in allowed and raw not in (None, ""):
                    try:
                        out.append(Constraint(col, kind, float(raw)))
                    except (TypeError, ValueError):
                        pass
                break
    return out


def seed_targets(seed_row: dict[str, Any], allowed: set[str],
                 popularity: Optional[int] = None) -> list[Constraint]:
    """A seed track's values → target constraints (the visible "more like this").

    Every numeric perceptual value becomes a target the form displays — the
    user sees exactly what "like this" means and can tweak any of it.
    """
    out = [Constraint(col, "target", float(v))
           for col, v in (seed_row or {}).items()
           if col in allowed and isinstance(v, (int, float)) and math.isfinite(float(v))]
    if popularity is not None and POPULARITY in allowed:
        out.append(Constraint(POPULARITY, "target", float(popularity)))
    return out


def _zscale(stats: dict[str, tuple[float, float]], col: str, diff: float) -> float:
    mean_std = stats.get(col)
    std = mean_std[1] if mean_std else 0.0
    return diff / std if std else 0.0  # a zero-spread axis can't rank anyone


def recommend(rows: dict[str, dict[str, Any]], constraints: list[Constraint],
              stats: dict[str, tuple[float, float]], *,
              exclude: Optional[set[str]] = None, limit: int = 20) -> list[dict[str, Any]]:
    """Filter + rank the cached population against the constraints.

    `rows`: track_id → feature dict (perceptual values + popularity merged).
    `stats`: column → (mean, std) for z-normalizing target distances so a
    30-bpm tempo miss and a 0.2 danceability miss compare honestly.
    Tracks missing a constrained value are excluded (can't verify → don't
    guess). Score = RMS of z-distances over the targets; min/max prune first.
    Returns [{id, score, values:{col: v for constrained cols}}...] ranked.
    """
    exclude = exclude or set()
    mins = [c for c in constraints if c.kind == "min"]
    maxs = [c for c in constraints if c.kind == "max"]
    targets = [c for c in constraints if c.kind == "target"]
    cols = {c.column for c in constraints}

    out: list[dict[str, Any]] = []
    for tid, feats in rows.items():
        if tid in exclude:
            continue
        vals: dict[str, float] = {}
        ok = True
        for col in cols:
            v = feats.get(col)
            if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                ok = False  # can't verify the constraint for this track
                break
            vals[col] = float(v)
        if not ok:
            continue
        if any(vals[c.column] < c.value for c in mins):
            continue
        if any(vals[c.column] > c.value for c in maxs):
            continue
        if targets:
            zs = [_zscale(stats, c.column, vals[c.column] - c.value) for c in targets]
            score = math.sqrt(sum(z * z for z in zs) / len(zs))
        else:
            score = 0.0
        out.append({"id": tid, "score": round(score, 4), "values": vals})

    out.sort(key=lambda r: (r["score"], r["id"]))
    return out[:limit]


def stats_from_frame(stats_df) -> dict[str, tuple[float, float]]:
    """feature_stats (the F2 mart, indexed by column) → {col: (mean, std)}."""
    if stats_df is None:
        return {}
    return {str(col): (float(row["mean"]), float(row["std"]))
            for col, row in stats_df.iterrows()}


def popularity_stats(popularity: dict[str, int]) -> Optional[tuple[float, float]]:
    """(mean, std) of the corpus popularity — the z-basis for its targets."""
    vals = list(popularity.values())
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return (mean, math.sqrt(var))
