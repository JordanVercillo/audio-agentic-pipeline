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
