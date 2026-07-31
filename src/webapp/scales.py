"""
scales.py — ONE registry of how a raw DSP column is NAMED and WORDED (P4.7.0).

Three vocabularies described the same six columns from three different files:

    _CHARACTER_DIMS  (analysis/clustering.py)  "Punchy · Smooth"     cluster names
    _SIGNATURE_DIMS  (webapp/analytics.py)     "louder than the …"   σ-vs-corpus prose
    _BANDS           (webapp/taste.py)         "laid-back"           absolute bands

The three word SETS are legitimately different — a cluster name wants a compact
noun, a signature wants a comparative, an absolute profile wants a plain-English
level — so this does NOT merge them. What it merges is everything that must
agree: WHICH columns are interpretable, and what each one is CALLED.

That mattered immediately. `rms_mean` was "Loudness" in the signature and
**"Energy"** in the absolute profile, while the perceptual catalog carries a
SEPARATE derived `energy` (a blend of RMS + onset + rolloff) alongside its own
`loudness_db`. So "Energy" named two different numbers on two pages — the exact
drift journal #27 is about, sitting in production. One display name per column
makes that unrepresentable.

FROZEN: the character words and their ORDER are imported from
`analysis/clustering._CHARACTER_DIMS`, never restated here. They generate
cluster labels, and a cluster label is an identity a visitor has seen (D-62) —
re-typing them anywhere would put a rename one typo away.
"""
from __future__ import annotations

from typing import Optional

from ..analysis.clustering import _CHARACTER_DIMS

# ── the registry ────────────────────────────────────────────────────────────
# column -> (display name, unit, comparative (hi, lo), absolute bands)
# `bands` is [(exclusive_upper, word), …] with a final 1e9 catch-all.
_SCALES: dict[str, tuple[str, str, Optional[tuple[str, str]], Optional[list]]] = {
    "tempo_bpm": (
        "Tempo", "bpm", ("faster", "slower"),
        [(90, "laid-back"), (120, "mid-tempo"), (140, "upbeat"), (1e9, "high-energy")]),
    "rms_mean": (
        # NOT "Energy" — see the module docstring; `energy` is a different,
        # derived feature in the perceptual catalog.
        "Loudness", "", ("louder", "quieter"),
        [(0.15, "gentle"), (0.25, "moderate"), (1e9, "loud")]),
    "spectral_centroid_mean": (
        "Brightness", "Hz", ("brighter", "darker"),
        [(1800, "warm"), (2800, "balanced"), (1e9, "bright")]),
    "zcr_mean": ("Noisiness", "", ("noisier", "smoother"), None),
    "harmonic_ratio": (
        "Harmonicity", "", ("more harmonic", "more percussive"), None),
    "onset_strength_mean": ("Punch", "", ("punchier", "gentler"), None),
    "rms_std": ("Dynamics", "", ("more dynamic", "steadier"), None),
    "spectral_rolloff_mean": ("Treble reach", "Hz", ("airier", "rounder"), None),
}

# Order is load-bearing for the signature (it ranks by |z| but ties resolve in
# insertion order) and for the /analytics projection, so it is stated once.
_SIGNATURE_ORDER = ("tempo_bpm", "rms_mean", "spectral_centroid_mean", "zcr_mean",
                    "harmonic_ratio", "onset_strength_mean", "rms_std",
                    "spectral_rolloff_mean")
_BAND_ORDER = ("tempo_bpm", "rms_mean", "spectral_centroid_mean")


def display_name(column: str) -> str:
    """What a visitor should see this column called — the same on every page."""
    spec = _SCALES.get(column)
    return spec[0] if spec else column


def unit(column: str) -> str:
    spec = _SCALES.get(column)
    return spec[1] if spec else ""


def signature_dims() -> list[tuple[str, str, str, str]]:
    """[(column, display, hi_word, lo_word)] — the σ-vs-corpus vocabulary."""
    out = []
    for col in _SIGNATURE_ORDER:
        name, _u, comp, _b = _SCALES[col]
        if comp:
            out.append((col, name, comp[0], comp[1]))
    return out


def bands() -> dict[str, tuple[str, str, list]]:
    """{column: (display, unit, bands)} — the absolute-profile vocabulary."""
    return {col: (_SCALES[col][0], _SCALES[col][1], _SCALES[col][3])
            for col in _BAND_ORDER if _SCALES[col][3]}


def character_dims() -> list[tuple[str, str, str]]:
    """[(column, Hi, Lo)] for cluster naming — the FROZEN list, imported not
    restated. Re-typing it here would put a cluster rename (and therefore an
    identity change, D-62) one typo away."""
    return list(_CHARACTER_DIMS)


def band_word(value: float, band_list: list[tuple[float, str]]) -> str:
    for upper, word in band_list:
        if value < upper:
            return word
    return band_list[-1][1]
