"""
features_view.py — the pure builder behind `GET /song/{id}/features` (D-66).

"Each song should let you dig into what ALL the audio features are, not just the
highlights." /song shows about nine; the cache stores 83 numeric columns per
track. This assembles every one of them with its meaning, its units and where it
sits in the corpus.

Three honesty rules the design turns on:

* **The dictionary is not restated here.** Descriptions come from the DSP
  layer via `raw_feature_dictionary.parquet`, so retuning an estimator can
  never leave this page describing the old behaviour (journal #27).
* **Percentiles use the SAME population as every other surface** — the mart is
  built over `excluded_from_aggregates`, so a rank here agrees with
  `tempo_pct` on track_card rather than quietly using its own denominator.
* **Some columns have no order.** A percentile on a pitch class is nonsense, so
  `direction: categorical` renders a value with no rank bar. And MFCC/chroma
  coefficients are not interpretable one at a time — the page says so instead
  of implying each number means something on its own.

Pure: dicts in, dict out. No I/O, no cache, no formatting decisions that a
template should own.
"""
from __future__ import annotations

from typing import Any, Optional

# Families whose individual coefficients carry no standalone meaning; the view
# groups them and leads with the caveat rather than 26 bare numbers.
_SHAPE_FAMILIES = ("mfcc_", "chroma_", "spectral_contrast_")

_GROUP_ORDER = ("Time & rhythm", "Level & dynamics", "Spectral shape",
                "Tonal & harmony", "Timbre fingerprint")


def _is_shape_family(column: str) -> bool:
    return column.startswith(_SHAPE_FAMILIES)


def _percentile(value: float, stat: dict) -> Optional[int]:
    """Rough rank of `value` within the corpus, from the stored quartiles.

    Deliberately coarse — interpolating between p25/p50/p75 is honest about
    what five summary numbers can support. A precise-looking "83rd percentile"
    from four anchors would be false precision.
    """
    if stat is None:
        return None
    lo, p25, p50, p75, hi = (stat.get("min"), stat.get("p25"), stat.get("p50"),
                             stat.get("p75"), stat.get("max"))
    if None in (lo, p25, p50, p75, hi):
        return None
    if value <= lo:
        return 0
    if value >= hi:
        return 100
    for a, b, base in ((lo, p25, 0), (p25, p50, 25), (p50, p75, 50), (p75, hi, 75)):
        if a <= value <= b:
            span = (b - a) or 1.0
            return int(round(base + 25 * (value - a) / span))
    return None


def build_feature_detail(features: dict, dictionary: list[dict],
                         stats: list[dict]) -> dict[str, Any]:
    """Group every stored numeric feature with its meaning and corpus context.

    `dictionary` and `stats` are the mart rows (list-of-dicts). Returns groups
    in a fixed order, each carrying rows and a `shape_note` when the group's
    numbers are only meaningful together.
    """
    doc = {d["column"]: d for d in dictionary}
    stat = {s["column"]: s for s in stats}

    rows_by_group: dict[str, list[dict]] = {}
    n_documented = 0
    for col in sorted(features):
        value = features.get(col)
        if not isinstance(value, (int, float)):
            continue                      # file_name / file_path / estimated_mode
        d = doc.get(col) or {}
        group = d.get("group") or "Other"
        categorical = "categorical" in str(d.get("direction", ""))
        shape = _is_shape_family(col)
        if d.get("description"):
            n_documented += 1
        rows_by_group.setdefault(group, []).append({
            "column": col,
            "value": value,
            "unit": d.get("unit", ""),
            "description": d.get("description", ""),
            "caveat": d.get("caveat", ""),
            "direction": d.get("direction", ""),
            "in_vector_77": bool(d.get("in_vector_77")),
            # No rank for an unorderable column, and none for a coefficient
            # whose standalone value carries no meaning.
            "percentile": (None if (categorical or shape)
                           else _percentile(float(value), stat.get(col))),
            "corpus_median": (stat.get(col) or {}).get("p50"),
            "categorical": categorical,
            "shape_only": shape,
        })

    groups = []
    for name in _GROUP_ORDER:
        rows = rows_by_group.pop(name, [])
        if not rows:
            continue
        shape_rows = [r for r in rows if r["shape_only"]]
        groups.append({
            "name": name,
            "rows": rows,
            "n": len(rows),
            # Stated once per group rather than repeated on 26 rows.
            "shape_note": (shape_rows[0]["caveat"] if shape_rows else ""),
            "collapsed": bool(shape_rows),   # long coefficient blocks start closed
        })
    for name, rows in rows_by_group.items():        # anything unforeseen, last
        groups.append({"name": name, "rows": rows, "n": len(rows),
                       "shape_note": "", "collapsed": False})

    total = sum(g["n"] for g in groups)
    return {
        "groups": groups,
        "n_features": total,
        "n_documented": n_documented,
        "n_in_vector": sum(1 for g in groups for r in g["rows"] if r["in_vector_77"]),
        "population_n": (stats[0].get("n") if stats else None),
    }
