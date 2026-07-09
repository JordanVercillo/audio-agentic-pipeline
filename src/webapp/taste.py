"""
taste.py — cache-sourced acoustic profile + drift for the dashboard (Epic A slice 3).

The dashboard now describes the VISITOR'S OWN analyzed songs (read from the shared
feature cache), not overlap with the owner corpus. Absolute acoustic bands +
recent-vs-all-time drift computed over their cached features (reuses the D-9
σ-shift). Genre/cluster labels arrive with Epic C.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

from ..analysis.drift import DRIFT_FEATURE_COLS, compute_taste_drift

# feature → (label, unit, ordered (upper_bound, word) bands; last is the catch-all)
_BANDS: dict[str, tuple[str, str, list[tuple[float, str]]]] = {
    "tempo_bpm": ("Tempo", "bpm",
                  [(90, "laid-back"), (120, "mid-tempo"), (140, "upbeat"), (1e9, "high-energy")]),
    "rms_mean": ("Energy", "",
                 [(0.15, "gentle"), (0.25, "moderate"), (1e9, "loud")]),
    "spectral_centroid_mean": ("Brightness", "Hz",
                               [(1800, "warm"), (2800, "balanced"), (1e9, "bright")]),
}


def _band(value: float, bands: list[tuple[float, str]]) -> str:
    for upper, word in bands:
        if value < upper:
            return word
    return bands[-1][1]


def _fmt(v: float) -> str:
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.0f}"


def absolute_profile(rows: list[dict]) -> Optional[dict[str, Any]]:
    """Describe the visitor's analyzed tracks in absolute acoustic bands (no corpus ref)."""
    if not rows:
        return None
    highlights: list[str] = []
    words: dict[str, str] = {}
    for col, (label, unit, bands) in _BANDS.items():
        vals = [r[col] for r in rows if r.get(col) is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        word = _band(mean, bands)
        words[label] = word
        unit_s = f" {unit}" if unit else ""
        highlights.append(f"{label}: {_fmt(mean)}{unit_s} — {word}")
    if not highlights:
        return None
    bits = ", ".join(f"{w} {label.lower()}" for label, w in words.items())
    return {
        "n": len(rows),
        "highlights": highlights,
        "message": f"Across your {len(rows)} analyzed tracks: {bits}.",
    }


def track_summary(features: Optional[dict]) -> Optional[dict[str, str]]:
    """A few interpretable features for the hover tooltip (Epic B)."""
    if not features:
        return None
    tempo = features.get("tempo_bpm")
    energy = features.get("rms_mean")
    bright = features.get("spectral_centroid_mean")
    return {
        "tempo": f"{tempo:.0f} bpm" if tempo is not None else "—",
        "energy": f"{energy:.2f}" if energy is not None else "—",
        "brightness": f"{bright:.0f} Hz" if bright is not None else "—",
    }


# Radar axes: (feature column, label, sensible min, max) for 0–1 normalization.
_RADAR = [
    ("tempo_bpm", "Tempo", 60.0, 180.0),
    ("rms_mean", "Energy", 0.0, 0.4),
    ("spectral_centroid_mean", "Brightness", 500.0, 4000.0),
    ("zcr_mean", "Noisiness", 0.0, 0.2),
    ("harmonic_ratio", "Harmonic", 0.0, 1.0),
    ("spectral_rolloff_mean", "Rolloff", 500.0, 8000.0),
]


def radar_svg(features: dict, size: int = 240) -> str:
    """Inline SVG radar of the interpretable features (deep-dive, Epic B)."""
    cx = cy = size / 2
    r = size * 0.36
    n = len(_RADAR)
    axes, labels, pts = [], [], []
    for i, (col, label, lo, hi) in enumerate(_RADAR):
        v = features.get(col)
        norm = 0.0 if v is None else max(0.0, min(1.0, (float(v) - lo) / (hi - lo)))
        ang = -math.pi / 2 + 2 * math.pi * i / n
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        pts.append(f"{cx + r * norm * cos_a:.1f},{cy + r * norm * sin_a:.1f}")
        axes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx + r * cos_a:.1f}" '
                    f'y2="{cy + r * sin_a:.1f}" class="radar-axis"/>')
        lx, ly = cx + (r + 16) * cos_a, cy + (r + 16) * sin_a
        anchor = "middle" if abs(cos_a) < 0.3 else ("start" if cos_a > 0 else "end")
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                      f'class="radar-label">{label}</text>')
    rings = "".join(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * frac:.1f}" class="radar-ring"/>'
        for frac in (0.33, 0.66, 1.0))
    return (
        f'<svg viewBox="0 0 {size} {size}" class="radar" role="img" '
        f'aria-label="acoustic feature radar">{rings}{"".join(axes)}'
        f'<polygon points="{" ".join(pts)}" class="radar-poly"/>{"".join(labels)}</svg>')


def loudness_svg(curve: Optional[list], width: int = 560, height: int = 140) -> str:
    """Inline SVG of the within-track loudness curve (F-v2, deep-dive).

    `curve` is the stored dBFS series. The y-axis auto-scales to the track's own
    min/max so the *dynamics* (build-ups, drops, quiet verses) are legible —
    axis labels carry the real dB values so it stays honest. Returns "" when
    there's nothing to draw (song analyzed before F-v2, or too few points).
    """
    pts = [float(v) for v in (curve or [])
           if v is not None and math.isfinite(float(v))]
    if len(pts) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 18
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    n = len(pts)
    base = pad_t + plot_h

    def x_of(i: int) -> float:
        return pad_l + (i / (n - 1)) * plot_w

    def y_of(v: float) -> float:
        return pad_t + (hi - v) / span * plot_h  # louder = higher on the chart

    line = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(pts))
    area = f"{pad_l:.1f},{base:.1f} {line} {pad_l + plot_w:.1f},{base:.1f}"
    return (
        f'<svg viewBox="0 0 {width} {height}" class="loudness" role="img" '
        f'aria-label="loudness over time in decibels">'
        f'<polygon class="loud-area" points="{area}"/>'
        f'<polyline class="loud-line" points="{line}" fill="none"/>'
        f'<text class="loud-ax" x="{pad_l}" y="{pad_t + 8}">{hi:.0f} dB</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base - 2}">{lo:.0f} dB</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base + 13}">start</text>'
        f'<text class="loud-ax" x="{pad_l + plot_w:.1f}" y="{base + 13}" '
        f'text-anchor="end">end</text>'
        f'</svg>')


def drift_over_rows(per_range_rows: dict[str, list[dict]]) -> Optional[dict[str, Any]]:
    """Recent-vs-all-time σ-shift over the visitor's OWN cached features (D-9).

    Needs short_term and long_term with ≥2 analyzed tracks each; returns None
    (rather than a noisy number) otherwise, and on a non-finite score.
    """
    cols: Optional[list[str]] = None
    frames: list[pd.DataFrame] = []
    for tr, rows in per_range_rows.items():
        if len(rows) < 2:
            continue
        df = pd.DataFrame(rows)
        present = [c for c in DRIFT_FEATURE_COLS if c in df.columns]
        if not present:
            continue
        cols = present
        sub = df[present].copy()
        sub["time_range"] = tr
        frames.append(sub)
    if not frames or cols is None:
        return None
    fact = pd.concat(frames, ignore_index=True)
    if not {"short_term", "long_term"}.issubset(set(fact["time_range"])):
        return None
    try:
        res = compute_taste_drift(fact, feature_cols=cols)
        score = float(res["drift_score"])
    except Exception:  # noqa: BLE001 — drift is nice-to-have, never fatal
        return None
    if not math.isfinite(score):
        return None
    return {
        "score": round(score, 3),
        "label": res.get("drift_label", ""),
        "n_short": int((fact["time_range"] == "short_term").sum()),
        "n_long": int((fact["time_range"] == "long_term").sum()),
    }
