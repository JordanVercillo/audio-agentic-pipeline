"""
analytics.py — the analytics & drift dashboard view logic (APP_SPEC Epic C).

Pure functions from cached data → template context: the user's acoustic
signature (top-|z| features vs the population), cluster composition per time
window + the movement highlight, and the cluster-map SVG (population dots dim,
the user's songs colored by cluster).

Chart rules (dataviz skill): categorical colors in FIXED order (never cycled),
palette validated against the dark surface, secondary encoding everywhere
(labels + gaps + legend — never color alone), text in ink/muted tokens.
"""

from __future__ import annotations

import math
from typing import Any, Optional

# Validated 6-color categorical palette (dark surface #171a21) — fixed order.
CLUSTER_COLORS = ["#5b8bf5", "#d4682f", "#a865d6", "#1f9994", "#e85d8a", "#a3871f"]


def cluster_color(cluster_id: int) -> str:
    return CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)]


# ── acoustic signature ──────────────────────────────────────────────────────
# feature → (label, high-word, low-word) — interpretable subset only.
_SIGNATURE_DIMS = [
    ("tempo_bpm", "Tempo", "faster", "slower"),
    ("rms_mean", "Loudness", "louder", "quieter"),
    ("spectral_centroid_mean", "Brightness", "brighter", "darker"),
    ("zcr_mean", "Noisiness", "noisier", "smoother"),
    ("harmonic_ratio", "Harmonicity", "more harmonic", "more percussive"),
    ("onset_strength_mean", "Punch", "punchier", "gentler"),
    ("rms_std", "Dynamics", "more dynamic", "steadier"),
    ("spectral_rolloff_mean", "Treble reach", "airier", "rounder"),
]


def acoustic_signature(user_rows: list[dict], population: list[dict],
                       top_n: int = 5) -> list[dict[str, Any]]:
    """The features where the user's mean deviates most from the population (|z|)."""
    if not user_rows or len(population) < 3:
        return []
    out: list[dict[str, Any]] = []
    for col, label, hi, lo in _SIGNATURE_DIMS:
        pop = [float(r[col]) for r in population
               if isinstance(r.get(col), (int, float))]
        usr = [float(r[col]) for r in user_rows
               if isinstance(r.get(col), (int, float))]
        if len(pop) < 3 or not usr:
            continue
        mean = sum(pop) / len(pop)
        var = sum((v - mean) ** 2 for v in pop) / len(pop)
        std = math.sqrt(var)
        if std == 0:
            continue
        z = (sum(usr) / len(usr) - mean) / std
        out.append({"feature": label, "z": round(z, 2),
                    "word": hi if z > 0 else lo,
                    "strength": min(1.0, abs(z) / 2.0)})  # bar fill, capped at 2σ
    out.sort(key=lambda d: -abs(d["z"]))
    return out[:top_n]


# ── cluster composition + movement ──────────────────────────────────────────
def cluster_composition(per_window: dict[str, list[int]],
                        labels: dict[str, str]) -> dict[str, Any]:
    """Per-window cluster shares + the biggest short-vs-long movement.

    per_window: {"short_term": [cluster_id, ...], ...} — the user's assigned songs.
    """
    shares: dict[str, list[dict]] = {}
    pct: dict[str, dict[int, float]] = {}
    for window, cids in per_window.items():
        if not cids:
            continue
        counts: dict[int, int] = {}
        for c in cids:
            counts[c] = counts.get(c, 0) + 1
        total = len(cids)
        pct[window] = {c: n / total for c, n in counts.items()}
        shares[window] = [
            {"cluster_id": c, "label": labels.get(str(c), f"Cluster {c}"),
             "share": round(100 * n / total), "count": n, "color": cluster_color(c)}
            for c, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ]

    movement: Optional[str] = None
    if "short_term" in pct and "long_term" in pct:
        deltas = {c: pct["short_term"].get(c, 0.0) - pct["long_term"].get(c, 0.0)
                  for c in set(pct["short_term"]) | set(pct["long_term"])}
        if deltas:
            c, d = max(deltas.items(), key=lambda kv: abs(kv[1]))
            if abs(d) >= 0.10:  # <10-point shifts aren't a story
                label = labels.get(str(c), f"Cluster {c}")
                direction = "toward" if d > 0 else "away from"
                movement = (f"Your recent listening moved {direction} “{label}” — "
                            f"{round(100 * pct['short_term'].get(c, 0))}% of the last 4 weeks "
                            f"vs {round(100 * pct['long_term'].get(c, 0))}% all-time.")
    return {"windows": shares, "movement": movement}


# ── the cluster map ─────────────────────────────────────────────────────────
def scatter_svg(population: list[dict], user_points: list[dict],
                width: int = 640, height: int = 400) -> Optional[str]:
    """The cluster map: population as dim context dots, the user's songs colored
    by cluster with a 2px surface ring and a native <title> tooltip each.

    Points: {x, y, cluster_id, [name, artist]} — only points with coords plot.
    """
    pts = [p for p in population if p.get("x") is not None]
    if len(pts) < 3:
        return None
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    pad = 22
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 2 * pad) / ((x1 - x0) or 1.0)
    sy = (height - 2 * pad) / ((y1 - y0) or 1.0)

    def px(p: dict) -> tuple[float, float]:
        return pad + (p["x"] - x0) * sx, pad + (p["y"] - y0) * sy

    user_ids = {p.get("id") for p in user_points}
    parts = [f'<svg viewBox="0 0 {width} {height}" class="cluster-map" role="img" '
             f'aria-label="acoustic cluster map">']
    for p in pts:  # context layer first
        if p.get("id") in user_ids:
            continue
        x, y = px(p)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" '
                     f'fill="{cluster_color(p["cluster_id"])}" opacity="0.28"/>')
    for p in user_points:  # the user's songs on top
        if p.get("x") is None:
            continue
        x, y = px(p)
        tip = f'{p.get("name", p.get("id", ""))} — {p.get("artist", "")}'.strip(" —")
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" '
            f'fill="{cluster_color(p["cluster_id"])}" stroke="#171a21" stroke-width="2">'
            f'<title>{tip}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)
