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

from markupsafe import escape  # SVG builders bypass Jinja autoescape (rendered |safe)

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
            f'<title>{escape(tip)}</title></circle>')  # track/artist names are untrusted
    parts.append("</svg>")
    return "".join(parts)


def popularity_context(user_pops: list, corpus_pops: list) -> Optional[dict[str, Any]]:
    """The taste-vs-popularity line (slice P) — FETCHED context, honestly framed.

    Spotify popularity is metadata we fetch (deprecated-not-removed upstream,
    journal #20), never an acoustic measure — the template labels it as such.
    Percentile framing needs a real baseline: with a corpus of ≥20 valued
    tracks we rank the visitor's mean against it (same at-or-below math as
    /explore); below that we fall back to Spotify's absolute 0–100 scale; and
    under 3 user values we say nothing rather than something noisy.
    """
    vals = [float(v) for v in user_pops if v is not None]
    if len(vals) < 3:
        return None
    mean = sum(vals) / len(vals)
    out: dict[str, Any] = {"mean": round(mean), "n": len(vals)}
    corpus = [float(v) for v in corpus_pops if v is not None]
    if len(corpus) >= 20:
        from .explore import percentile_of
        pct = percentile_of(mean, corpus)
        out["basis"] = "corpus"
        if pct >= 50:
            out["line"] = (f"Your rotation averages {out['mean']}/100 popularity — "
                           f"more mainstream than {pct}% of the corpus.")
        else:
            out["line"] = (f"Your rotation averages {out['mean']}/100 popularity — "
                           f"more obscure than {100 - pct}% of the corpus.")
    else:
        out["basis"] = "absolute"
        band = ("solidly mainstream" if mean >= 65
                else "a mixed rotation" if mean >= 40 else "deep-cut territory")
        out["line"] = (f"Your rotation averages {out['mean']}/100 on Spotify's "
                       f"popularity scale — {band}.")
    return out


# ── average loudness arc (roll-up of the F-v2 within-track curves) ───────────
def _resample_unit(curve: Optional[list], grid: int) -> Optional[list[float]]:
    """One stored dBFS curve → a `grid`-point series over track-fraction 0→1,
    min-max normalized to its OWN dynamic range (0 = the track's quietest point,
    1 = its loudest). None if the curve is too short or has no dynamics — so a
    silent/constant track can't drag the average toward a flat line.
    """
    pts = [float(v) for v in (curve or [])
           if v is not None and math.isfinite(float(v))]
    if len(pts) < 8:
        return None
    lo, hi = min(pts), max(pts)
    span = hi - lo
    if span <= 0:
        return None
    norm = [(v - lo) / span for v in pts]
    n = len(norm)
    out: list[float] = []
    for g in range(grid):
        pos = g / (grid - 1) * (n - 1)  # fraction-aligned source position
        i = int(pos)
        if i >= n - 1:
            out.append(norm[-1])
        else:
            frac = pos - i
            out.append(norm[i] * (1 - frac) + norm[i + 1] * frac)
    return out


def average_loudness_arc(curves: Optional[list], grid: int = 96,
                         min_tracks: int = 5) -> Optional[dict[str, Any]]:
    """The average loudness *shape* across the user's analyzed tracks (F-v2 roll-up).

    Each track's stored dBFS curve is normalized to its own dynamic range and
    resampled onto a common 0→1 timeline, then summarized pointwise by three
    quantiles — so this reads the shape of a typical song (build-ups, drops,
    fades), independent of how loudly any one track was mastered (absolute level
    lives in the signature's "Loudness" dim, so this doesn't duplicate it). The
    central line is the median (p50); the band is the middle 50% (p25–p75), an
    honest read on how much the tracks vary at each point — and, being quantiles,
    the band brackets the line by construction. None under `min_tracks` curves.
    """
    arcs = [a for a in (_resample_unit(c, grid) for c in (curves or [])) if a]
    if len(arcs) < min_tracks:
        return None
    mid, lo, hi = [], [], []
    for g in range(grid):
        col = sorted(a[g] for a in arcs)
        m = len(col)
        lo.append(col[int(0.25 * (m - 1))])
        mid.append(col[int(0.50 * (m - 1))])
        hi.append(col[int(0.75 * (m - 1))])
    return {"n": len(arcs), "grid": grid, "mid": mid, "lo": lo, "hi": hi}


def loudness_arc_svg(arc: Optional[dict], width: int = 560, height: int = 150) -> str:
    """Area chart of the average loudness arc + a middle-50% spread band. Reuses
    the deep-dive loudness styling; the y-axis is relative (louder/quieter)
    because each track was normalized to its own range. "" when arc is None."""
    if not arc:
        return ""
    mid, lo, hi, grid = arc["mid"], arc["lo"], arc["hi"], arc["grid"]
    pad_l, pad_r, pad_t, pad_b = 8, 8, 12, 18
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    base = pad_t + plot_h

    def x_of(i: int) -> float:
        return pad_l + (i / (grid - 1)) * plot_w

    def y_of(v: float) -> float:
        return pad_t + (1 - v) * plot_h  # louder (1) = higher on the chart

    band_top = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(hi))
    band_bot = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}"
                        for i, v in reversed(list(enumerate(lo))))
    mid_line = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(mid))
    area = f"{pad_l:.1f},{base:.1f} {mid_line} {pad_l + plot_w:.1f},{base:.1f}"

    return (
        f'<svg viewBox="0 0 {width} {height}" class="loudness" role="img" '
        f'aria-label="average loudness shape across your tracks, start to end">'
        f'<polygon class="loud-band" points="{band_top} {band_bot}"/>'
        f'<polygon class="loud-area" points="{area}"/>'
        f'<polyline class="loud-line" points="{mid_line}" fill="none"/>'
        f'<text class="loud-ax" x="{pad_l}" y="{pad_t + 8}">louder</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base - 2}">quieter</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base + 13}">start</text>'
        f'<text class="loud-ax" x="{pad_l + plot_w:.1f}" y="{base + 13}" '
        f'text-anchor="end">end</text></svg>')
