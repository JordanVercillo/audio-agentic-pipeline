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
from . import scales

# feature → (label, unit, ordered (upper_bound, word) bands; last is the catch-all)
# P4.7.0: derived from the ONE registry. `rms_mean` used to be labelled
# "Energy" here while the signature called it "Loudness" and the perceptual
# catalog carried a SEPARATE derived `energy` — one column, two visitor-facing
# names, two different numbers (scales.py).
_BANDS = scales.bands()


def _band(value: float, bands: list[tuple[float, str]]) -> str:
    return scales.band_word(value, bands)


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


_FADE_DROP_DB = 8.0     # "arrived at full" = within this many dB of the sustained level
_FADE_MIN_DEPTH_DB = 20.0  # the edge must start/end at least this far below full —
#                            separates a real fade FROM SILENCE (25–45 dB down) from a
#                            merely quiet intro (~6–12 dB down)
_FADE_MIN_FRAC = 0.04   # ignore fades shorter than 4% of the track (onset ramps)


def fade_bounds(curve: Optional[list]) -> tuple[Optional[float], Optional[float]]:
    """Fade-in-end and fade-out-start as fractions of the track (0–1), from the
    stored loudness curve (F-v2c) — rebuilds Spotify audio-analysis'
    end_of_fade_in / start_of_fade_out. Pure over data we already have (no
    re-extraction). None unless the track genuinely fades from/to near-silence:
    the edge must sit ≥15 dB below the sustained level AND take ≥3% of the track
    to arrive — so a quiet intro or a bare onset ramp does NOT count as a fade.
    """
    pts = [float(v) for v in (curve or [])
           if v is not None and math.isfinite(float(v))]
    n = len(pts)
    if n < 5:
        return (None, None)
    full = sorted(pts)[int(0.8 * (n - 1))]   # ~80th pct = sustained loud level
    reach = full - _FADE_DROP_DB             # loudness has "arrived" at full
    deep = full - _FADE_MIN_DEPTH_DB         # edge is quiet enough to be a true fade

    fin_frac = None
    if pts[0] <= deep:                       # starts near silence
        fin = 0
        while fin < n and pts[fin] < reach:
            fin += 1
        if fin < n and fin / (n - 1) >= _FADE_MIN_FRAC:
            fin_frac = fin / (n - 1)

    fout_frac = None
    if pts[-1] <= deep:                       # ends near silence
        fout = n - 1
        while fout >= 0 and pts[fout] < reach:
            fout -= 1
        if fout >= 0 and (1.0 - fout / (n - 1)) >= _FADE_MIN_FRAC:
            fout_frac = fout / (n - 1)
    return (fin_frac, fout_frac)


def loudness_svg(curve: Optional[list], beat_times: Optional[list] = None,
                 duration_sec: Optional[float] = None, meter: int = 4,
                 width: int = 560, height: int = 140) -> str:
    """Inline SVG of the within-track loudness curve (F-v2, deep-dive).

    `curve` is the stored dBFS series. The y-axis auto-scales to the track's own
    min/max so the *dynamics* (build-ups, drops, quiet verses) are legible —
    axis labels carry the real dB values so it stays honest. Detected fade-in /
    fade-out regions (F-v2c) are shaded, and — when `beat_times` (seconds) +
    `duration_sec` are given — a **bar grid** is drawn as ticks below the curve:
    every `meter`-th real detected beat, so the spacing is one true measure
    (~4× sparser than a full beat grid, legible). Real beat positions, so the
    spacing tracks tempo; the downbeat *phase* is approximate. Returns "" when
    there's nothing to draw.
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

    # Fade regions (F-v2c) — shaded band + boundary marker + label.
    fin_frac, fout_frac = fade_bounds(pts)
    fades = ""
    if fin_frac:
        fx = pad_l + fin_frac * plot_w
        fades += (f'<rect class="loud-fade" x="{pad_l:.1f}" y="{pad_t:.1f}" '
                  f'width="{fin_frac * plot_w:.1f}" height="{plot_h:.1f}"/>'
                  f'<line class="loud-fade-line" x1="{fx:.1f}" y1="{pad_t:.1f}" '
                  f'x2="{fx:.1f}" y2="{base:.1f}"/>'
                  f'<text class="loud-fade-t" x="{fx + 3:.1f}" y="{pad_t + 8:.1f}">fade in</text>')
    if fout_frac:
        fx = pad_l + fout_frac * plot_w
        fades += (f'<rect class="loud-fade" x="{fx:.1f}" y="{pad_t:.1f}" '
                  f'width="{(1 - fout_frac) * plot_w:.1f}" height="{plot_h:.1f}"/>'
                  f'<line class="loud-fade-line" x1="{fx:.1f}" y1="{pad_t:.1f}" '
                  f'x2="{fx:.1f}" y2="{base:.1f}"/>'
                  f'<text class="loud-fade-t" x="{fx - 3:.1f}" y="{pad_t + 8:.1f}" '
                  f'text-anchor="end">fade out</text>')
    # Bar grid (F-v2c): every meter-th real beat → measure-spaced ticks below
    # the curve (a full beat grid is ~1px/beat at this width — a solid smear).
    beats = ""
    if beat_times and duration_sec and duration_sec > 0:
        step = max(1, int(meter))
        bt = [float(t) for t in beat_times[::step]
              if isinstance(t, (int, float)) and 0.0 <= float(t) <= duration_sec]
        if 0 < len(bt) <= 400:
            beats = "".join(
                f'<line class="loud-beat" x1="{pad_l + (t / duration_sec) * plot_w:.1f}" '
                f'y1="{base:.1f}" x2="{pad_l + (t / duration_sec) * plot_w:.1f}" '
                f'y2="{base + 4:.1f}"/>' for t in bt)

    return (
        f'<svg viewBox="0 0 {width} {height}" class="loudness" role="img" '
        f'aria-label="loudness over time in decibels">'
        f'<polygon class="loud-area" points="{area}"/>'
        f'<polyline class="loud-line" points="{line}" fill="none"/>{fades}{beats}'
        f'<text class="loud-ax" x="{pad_l}" y="{pad_t + 8}">{hi:.0f} dB</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base - 2}">{lo:.0f} dB</text>'
        f'<text class="loud-ax" x="{pad_l}" y="{base + 13}">start</text>'
        f'<text class="loud-ax" x="{pad_l + plot_w:.1f}" y="{base + 13}" '
        f'text-anchor="end">end</text>'
        f'</svg>')


# Section ribbon (F-v3). A dedicated palette — cluster colors keep their
# app-wide meaning (sound clusters); section letters are per-song identities.
_SECTION_COLORS = ["#7aa2ff", "#f2a65a", "#67c9a5", "#c792ea", "#e0648a", "#8d99ae"]
_SECTION_LETTERS = "ABCDEFGH"
_PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _mmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def sections_svg(sections: Optional[list], duration_sec: Optional[float],
                 width: int = 560, height: int = 46) -> str:
    """Inline SVG ribbon of the detected sections (F-v3, deep-dive).

    Same LETTER/color = the same-sounding part (repeat identity from
    self-similarity). Letters follow first appearance — deliberately NOT
    "chorus"/"verse": semantic labels aren't reliably inferable, so we don't
    claim them. Hover a section for its span, tempo, loudness, and key.
    Returns "" when there's nothing to draw.
    """
    secs = sections or []
    if len(secs) < 1 or not duration_sec or duration_sec <= 0:
        return ""
    pad_l, pad_r, pad_t, bar_h = 8, 8, 4, 24
    plot_w = width - pad_l - pad_r
    base = pad_t + bar_h
    parts = [f'<svg viewBox="0 0 {width} {height}" class="sections" role="img" '
             f'aria-label="detected song sections">']
    for s in secs:
        x0 = pad_l + (float(s["start"]) / duration_sec) * plot_w
        x1 = pad_l + (min(float(s["end"]), duration_sec) / duration_sec) * plot_w
        w = max(x1 - x0, 1.0)
        lab = int(s.get("label", 0))
        letter = _SECTION_LETTERS[lab % len(_SECTION_LETTERS)]
        color = _SECTION_COLORS[lab % len(_SECTION_COLORS)]
        key, mode = s.get("key", -1), s.get("mode", "")
        keyname = f"{_PITCHES[key]} {mode}" if 0 <= key <= 11 and mode else "—"
        loud = s.get("loudness_db")
        # "beat rate", NOT "bpm": this is 60·beats/duration within the span, a
        # DENSITY — the headline tempo is beat_track's dominant periodicity.
        # They legitimately differ (sparse intro/outro beats drag density down),
        # and labelling both "bpm" made the page look self-contradictory.
        tip = (f"{letter} · {_mmss(s['start'])}–{_mmss(s['end'])} · "
               f"{s.get('tempo_bpm', 0):.0f} beats/min avg · "
               f"{loud if loud is not None else '—'} dB · {keyname}")
        parts.append(
            f'<rect class="sec-rect" x="{x0:.1f}" y="{pad_t}" width="{w:.1f}" '
            f'height="{bar_h}" fill="{color}"><title>{tip}</title></rect>')
        if w >= 16:
            parts.append(f'<text class="sec-letter" x="{x0 + w / 2:.1f}" '
                         f'y="{pad_t + bar_h / 2 + 3.5:.1f}" '
                         f'text-anchor="middle">{letter}</text>')
    parts.append(f'<text class="loud-ax" x="{pad_l}" y="{base + 13}">0:00</text>')
    parts.append(f'<text class="loud-ax" x="{pad_l + plot_w:.1f}" y="{base + 13}" '
                 f'text-anchor="end">{_mmss(duration_sec)}</text>')
    parts.append("</svg>")
    return "".join(parts)


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
