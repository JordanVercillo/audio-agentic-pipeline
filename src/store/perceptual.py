"""
perceptual.py — the derived perceptual feature layer, ``perceptual-v1``
(VISION_SPECS Epic F, slice F1).

Spotify deprecated its audio-features endpoint; this rebuilds the beloved
fields — and adds our own — as a PURE TRANSFORM over the 82 columns already in
the feature cache. No re-extraction; versioned like a model; every feature
carries an honest tier:

    measured      read directly off the DSP output (tempo, key, mode, duration,
                  loudness in dBFS)
    derived       a documented blend of measured features, percentile-calibrated
                  0–1 against the cached population (energy, danceability,
                  acousticness, speechiness, brightness, punch, dynamics)
    experimental  a labeled proxy, shown with a caveat (valence_proxy)

Deliberately NOT here (F-v2, needs frame-level audio): time_signature,
instrumentalness — summary statistics cannot see vocals, and a fake proxy
would cost the tier system its credibility. liveness is out entirely.

Percentile calibration means a track's 0–1 value is its standing WITHIN the
cached population ("more danceable than 80% of cached songs") — recomputed on
each mart build as the population grows, which is why the version travels with
every row.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from .cache import FeatureCache

PERCEPTUAL_VERSION = "perceptual-v1"

_EPS = 1e-9

# Inputs a row must have to be transformable (the ghost-row guard, journal #13).
_REQUIRED = [
    "tempo_bpm", "rms_mean", "rms_std", "zcr_mean", "spectral_centroid_mean",
    "spectral_flatness_mean", "harmonic_ratio", "onset_strength_mean",
    "onset_strength_std", "beats_per_sec", "duration_sec",
]

# The catalog: every feature the explorer can offer, with its honest tier.
# (column, tier, unit, friendly name, description)
CATALOG: list[dict[str, str]] = [
    # ── measured (read off the DSP) ──
    {"column": "tempo", "tier": "measured", "unit": "bpm", "friendly": "Tempo",
     "description": "Estimated tempo from beat tracking."},
    {"column": "key", "tier": "measured", "unit": "pitch class",
     "friendly": "Key", "description": "Estimated musical key (0=C … 11=B)."},
    {"column": "mode", "tier": "measured", "unit": "major=1",
     "friendly": "Mode", "description": "Estimated modality: major (1) or minor (0)."},
    {"column": "duration_sec", "tier": "measured", "unit": "s",
     "friendly": "Duration", "description": "Track length in seconds."},
    {"column": "loudness_db", "tier": "measured", "unit": "dBFS",
     "friendly": "Loudness", "description": "Overall loudness: 20·log10(mean RMS), dB full-scale."},
    # ── derived (documented blends, percentile-calibrated 0–1) ──
    {"column": "energy", "tier": "derived", "unit": "0–1", "friendly": "Energy",
     "description": "Perceived intensity: RMS level + onset strength + spectral rolloff, ranked against the population."},
    {"column": "danceability", "tier": "derived", "unit": "0–1", "friendly": "Danceability",
     "description": "Dance-floor fit: tempo near the 120 bpm sweet spot × pulse regularity × beat density."},
    {"column": "acousticness", "tier": "derived", "unit": "0–1", "friendly": "Acousticness",
     "description": "Acoustic character: harmonic content high; brightness, noisiness and flatness low."},
    {"column": "speechiness", "tier": "derived", "unit": "0–1", "friendly": "Speechiness",
     "description": "Spoken-word character: zero-crossing rate + spectral flatness high, harmonicity low."},
    {"column": "brightness", "tier": "derived", "unit": "0–1", "friendly": "Brightness",
     "description": "Spectral centroid, ranked against the population."},
    {"column": "punch", "tier": "derived", "unit": "0–1", "friendly": "Punch",
     "description": "Onset strength (attack energy), ranked against the population."},
    {"column": "dynamics", "tier": "derived", "unit": "0–1", "friendly": "Dynamics",
     "description": "Loudness variability (RMS std), ranked against the population."},
    # ── experimental (labeled proxies) ──
    {"column": "valence_proxy", "tier": "experimental", "unit": "0–1",
     "friendly": "Valence (proxy)",
     "description": "Mood proxy: major mode + tempo + brightness. A heuristic, not a trained "
                    "model — treat as directional only."},
]


def _pct(series: pd.Series) -> pd.Series:
    """Percentile-calibrate to (0, 1]: a value's standing within the population."""
    return series.rank(pct=True, method="average")


def _z(series: pd.Series) -> pd.Series:
    std = series.std()
    if not std or math.isnan(std):
        return series * 0.0
    return (series - series.mean()) / std


def _mode_num(v: Any) -> Optional[float]:
    if isinstance(v, str):
        return 1.0 if v.lower().startswith("maj") else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def compute_perceptual(cache: FeatureCache) -> pd.DataFrame:
    """The perceptual-v1 transform over every complete cached track.

    Returns a DataFrame keyed on the bridge key with every CATALOG column +
    ``version``. Incomplete rows (e.g. never-acquired tracks) sit out.
    """
    feats = cache.all_features()
    rows = [{"spotify_track_id": tid, **f} for tid, f in feats.items()
            if all(isinstance(f.get(c), (int, float)) and f.get(c) is not None
                   for c in _REQUIRED)]
    if not rows:
        return pd.DataFrame(columns=["spotify_track_id", "version"])
    df = pd.DataFrame(rows)

    out = pd.DataFrame({"spotify_track_id": df["spotify_track_id"]})

    # ── measured ──
    out["tempo"] = df["tempo_bpm"].astype(float)
    out["key"] = df.get("estimated_key", pd.Series([None] * len(df))).map(
        lambda v: int(v) if isinstance(v, (int, float)) and not pd.isna(v) else None)
    out["mode"] = df.get("estimated_mode", pd.Series([None] * len(df))).map(_mode_num)
    out["duration_sec"] = df["duration_sec"].astype(float)
    out["loudness_db"] = df["rms_mean"].map(
        lambda r: round(20.0 * math.log10(max(float(r), _EPS)), 2))

    # ── derived blends → percentile-calibrated 0–1 ──
    energy_raw = _z(df["rms_mean"]) + _z(df["onset_strength_mean"]) \
        + _z(df.get("spectral_rolloff_mean", df["spectral_centroid_mean"]))
    out["energy"] = _pct(energy_raw)

    tempo_band = np.exp(-(((df["tempo_bpm"] - 120.0) / 30.0) ** 2))  # sweet spot ~120
    pulse_clarity = df["onset_strength_mean"] / (df["onset_strength_std"] + _EPS)
    dance_raw = _z(tempo_band) + _z(pulse_clarity) + _z(df["beats_per_sec"])
    out["danceability"] = _pct(dance_raw)

    acoustic_raw = _z(df["harmonic_ratio"]) - _z(df["spectral_centroid_mean"]) \
        - _z(df["spectral_flatness_mean"]) - _z(df["zcr_mean"])
    out["acousticness"] = _pct(acoustic_raw)

    speech_raw = _z(df["zcr_mean"]) + _z(df["spectral_flatness_mean"]) \
        - _z(df["harmonic_ratio"])
    out["speechiness"] = _pct(speech_raw)

    out["brightness"] = _pct(df["spectral_centroid_mean"])
    out["punch"] = _pct(df["onset_strength_mean"])
    out["dynamics"] = _pct(df["rms_std"])

    # ── experimental ──
    mode_series = out["mode"].fillna(0.5)  # unknown mode sits in the middle
    valence_raw = _z(mode_series) + _z(df["tempo_bpm"]) + _z(df["spectral_centroid_mean"])
    out["valence_proxy"] = _pct(valence_raw)

    for col in ("energy", "danceability", "acousticness", "speechiness",
                "brightness", "punch", "dynamics", "valence_proxy"):
        out[col] = out[col].round(4)
    out["version"] = PERCEPTUAL_VERSION
    return out


def compute_feature_stats(df: pd.DataFrame) -> pd.DataFrame:
    """The distribution mart (F2): one row per catalog feature — moments,
    percentiles, and a fixed histogram — so /explore can draw population
    charts without ever shipping raw rows.

    Binning is deterministic per feature class (comparable across rebuilds):
        mode              2 bins  [-0.5, 0.5, 1.5]
        key              12 bins  [-0.5 … 11.5]
        0–1 calibrated   20 bins  [0 … 1]
        other measured   20 bins  [min … max] of the current population
    """
    rows: list[dict[str, Any]] = []
    for spec in CATALOG:
        col = spec["column"]
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        if col == "mode":
            edges = np.array([-0.5, 0.5, 1.5])
        elif col == "key":
            edges = np.arange(-0.5, 12.0, 1.0)
        elif spec["tier"] in ("derived", "experimental"):
            edges = np.linspace(0.0, 1.0, 21)
        else:
            lo, hi = float(vals.min()), float(vals.max())
            if lo == hi:  # degenerate population — one bin around the value
                lo, hi = lo - 0.5, hi + 0.5
            edges = np.linspace(lo, hi, 21)
        counts, _ = np.histogram(vals, bins=edges)
        q = vals.quantile([0.05, 0.25, 0.50, 0.75, 0.95])
        rows.append({
            "column": col, "tier": spec["tier"], "unit": spec["unit"],
            "friendly": spec["friendly"], "description": spec["description"],
            "n": int(len(vals)),
            "mean": round(float(vals.mean()), 4),
            "std": round(float(vals.std(ddof=0)), 4),
            "min": round(float(vals.min()), 4),
            "p5": round(float(q.loc[0.05]), 4), "p25": round(float(q.loc[0.25]), 4),
            "p50": round(float(q.loc[0.50]), 4), "p75": round(float(q.loc[0.75]), 4),
            "p95": round(float(q.loc[0.95]), 4),
            "max": round(float(vals.max()), 4),
            "bin_edges": [round(float(e), 4) for e in edges],
            "bin_counts": [int(c) for c in counts],
            "version": PERCEPTUAL_VERSION,
        })
    return pd.DataFrame(rows)


def persist_perceptual(cache: FeatureCache, df: pd.DataFrame) -> int:
    """Upsert the transform into the cache's track_perceptual table."""
    n = 0
    now = datetime.now(timezone.utc)
    for _, row in df.iterrows():
        payload = {k: (None if pd.isna(v) else v) for k, v in row.items()
                   if k not in ("spotify_track_id", "version")}
        cache.upsert_perceptual(row["spotify_track_id"], payload,
                                version=row["version"], computed_at=now)
        n += 1
    return n


def catalog_frame() -> pd.DataFrame:
    """The feature catalog as a DataFrame (the /explore picker's source)."""
    return pd.DataFrame(CATALOG)
