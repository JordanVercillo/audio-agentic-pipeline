"""
explore.py — the Audio-Feature Explorer view logic (VISION_SPECS Epic F, F3).

Pure functions from the F1/F2 marts → template context: the tier-grouped
feature picker, the population histogram with the visitor's tracks overlaid,
exact percentile chips, the feature×feature scatter colored by the Epic-C
sound clusters, and the per-window strip.

Chart rules (dataviz skill, loaded in Epic C): population bars are ONE series
(no legend needed beyond the inline "everyone · you" key); identity is never
color-alone (labels + position + rings); 2px gaps between bars; text wears ink
tokens, never series colors. The visitor's marks use the brand green — the
"you" accent everywhere in this app; cluster hues stay reserved for clusters.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .analytics import cluster_color

_MARTS = Path(__file__).resolve().parent.parent.parent / "data" / "marts"

_BAR = "#7aa2ff"      # population series (the app's info accent)
_YOU = "#1db954"      # the visitor — brand green, as on every other page
_SURFACE = "#171a21"  # panel surface, for mark rings

_WINDOW_LABELS = {"short_term": "Last 4 weeks", "medium_term": "Last 6 months",
                  "long_term": "All time"}


# ── mart loaders (cached per process; rebuilt marts need an app restart) ────
@lru_cache(maxsize=1)
def load_catalog() -> Optional[pd.DataFrame]:
    path = _MARTS / "feature_catalog.parquet"
    return pd.read_parquet(path) if path.exists() else None


@lru_cache(maxsize=1)
def load_stats() -> Optional[pd.DataFrame]:
    path = _MARTS / "feature_stats.parquet"
    return pd.read_parquet(path).set_index("column") if path.exists() else None


def catalog_groups(catalog: pd.DataFrame) -> list[dict[str, Any]]:
    """The picker: features grouped by tier, in catalog order."""
    order = ["measured", "derived", "experimental"]
    return [{"tier": tier,
             "features": catalog[catalog["tier"] == tier].to_dict("records")}
            for tier in order if (catalog["tier"] == tier).any()]


# ── percentiles (exact, against the live population) ────────────────────────
def percentile_of(value: float, population: list[float]) -> int:
    """The share of the population at or below `value`, as a whole percent."""
    if not population:
        return 50
    below = sum(1 for v in population if v <= value)
    return round(100 * below / len(population))


# ── the distribution view ───────────────────────────────────────────────────
def histogram_svg(stats_row: pd.Series, user_values: list[float],
                  width: int = 640, height: int = 220) -> str:
    """Population histogram (one series) + the visitor's tracks as ringed dots."""
    edges = list(stats_row["bin_edges"])
    counts = list(stats_row["bin_counts"])
    n_bins = len(counts)
    pad_l, pad_r, pad_b, pad_t = 10, 10, 26, 8
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    max_c = max(counts) or 1
    lo, hi = edges[0], edges[-1]
    span = (hi - lo) or 1.0

    def x_of(v: float) -> float:
        return pad_l + (min(max(v, lo), hi) - lo) / span * plot_w

    parts = [f'<svg viewBox="0 0 {width} {height}" class="hist" role="img" '
             f'aria-label="population distribution">']
    bar_w = plot_w / n_bins
    for i, c in enumerate(counts):
        h = (c / max_c) * plot_h
        x = pad_l + i * bar_w
        y = pad_t + plot_h - h
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{y:.1f}" width="{max(bar_w - 2, 1):.1f}" '
            f'height="{h:.1f}" rx="2" fill="{_BAR}" opacity="0.55">'
            f'<title>{edges[i]:g}–{edges[i + 1]:g}: {c} songs</title></rect>')
    baseline = pad_t + plot_h
    for v in user_values:
        parts.append(
            f'<circle cx="{x_of(v):.1f}" cy="{baseline - 6:.1f}" r="5" '
            f'fill="{_YOU}" stroke="{_SURFACE}" stroke-width="2">'
            f'<title>you: {v:g}</title></circle>')
    parts.append(f'<text x="{pad_l}" y="{height - 8}" class="axis">{edges[0]:g}</text>')
    parts.append(f'<text x="{width - pad_r}" y="{height - 8}" text-anchor="end" '
                 f'class="axis">{edges[-1]:g}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ── the feature×feature scatter ─────────────────────────────────────────────
def scatter_xy_svg(points: list[dict], user_ids: set[str],
                   x_label: str, y_label: str,
                   width: int = 640, height: int = 420) -> Optional[str]:
    """All cached tracks in (x, y) feature space, colored by sound cluster;
    the visitor's tracks ringed and on top. Points: {id, x, y, cluster_id, name}."""
    pts = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if len(pts) < 3:
        return None
    pad = 34
    xs, ys = [p["x"] for p in pts], [p["y"] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 2 * pad) / ((x1 - x0) or 1.0)
    sy = (height - 2 * pad) / ((y1 - y0) or 1.0)

    def px(p: dict) -> tuple[float, float]:
        return pad + (p["x"] - x0) * sx, height - pad - (p["y"] - y0) * sy

    parts = [f'<svg viewBox="0 0 {width} {height}" class="cluster-map" role="img" '
             f'aria-label="{x_label} vs {y_label}">']
    mine = []
    for p in pts:
        x, y = px(p)
        color = cluster_color(p["cluster_id"]) if p.get("cluster_id") is not None \
            else "#9aa0ac"
        if p["id"] in user_ids:
            mine.append((x, y, color, p.get("name", p["id"])))
        else:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" '
                         f'fill="{color}" opacity="0.3"/>')
    for x, y, color, name in mine:  # the visitor's songs on top, ringed
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{color}" '
                     f'stroke="{_SURFACE}" stroke-width="2">'
                     f'<title>{name}</title></circle>')
    parts.append(f'<text x="{width / 2:.0f}" y="{height - 8}" text-anchor="middle" '
                 f'class="axis">{x_label} →</text>')
    parts.append(f'<text x="12" y="{height / 2:.0f}" class="axis" '
                 f'transform="rotate(-90 12 {height / 2:.0f})" '
                 f'text-anchor="middle">{y_label} →</text>')
    parts.append("</svg>")
    return "".join(parts)


# ── the per-window strip ────────────────────────────────────────────────────
def window_strip(per_window_values: dict[str, list[float]], unit: str,
                 ) -> Optional[dict[str, Any]]:
    """Mean per time window + the recent-vs-all-time delta sentence."""
    means = {w: sum(v) / len(v) for w, v in per_window_values.items() if v}
    if not means:
        return None
    windows = [{"window": w, "label": _WINDOW_LABELS.get(w, w),
                "mean": round(means[w], 3 if abs(means[w]) < 10 else 1)}
               for w in ("short_term", "medium_term", "long_term") if w in means]
    delta_line = None
    if "short_term" in means and "long_term" in means:
        d = means["short_term"] - means["long_term"]
        if abs(d) > 1e-9:
            val = f"{abs(d):.2f}" if abs(d) < 10 else f"{abs(d):.0f}"
            unit_s = f" {unit}" if unit and unit not in ("0–1",) else ""
            delta_line = (f"Your last 4 weeks run {val}{unit_s} "
                          f"{'higher' if d > 0 else 'lower'} than your all-time.")
    return {"windows": windows, "delta": delta_line}
