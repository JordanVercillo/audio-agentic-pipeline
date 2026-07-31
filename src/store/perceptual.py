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
import os
import time
from datetime import datetime, timezone
from pathlib import Path
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
    {"column": "time_signature", "tier": "measured", "unit": "beats/bar",
     "friendly": "Time signature",
     "description": "Estimated beats per bar from beat-accent periodicity. Coarse: duple "
                    "meter is reported as 4 (2/4 and 4/4 aren't distinguishable from accents), "
                    "so this surfaces the odd/compound meters (3, 5, 6, 7) against a 4 default."},
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


def compute_perceptual(cache: FeatureCache, *,
                       feats: Optional[dict[str, dict]] = None,
                       twins: Optional[set[str]] = None) -> pd.DataFrame:
    """The perceptual-v1 transform over every complete cached track.

    Returns a DataFrame keyed on the bridge key with every CATALOG column +
    ``version``. Incomplete rows (e.g. never-acquired tracks) sit out.
    O3b: flagged duplicate twins sit out too — the perceptual plane counts
    each RECORDING once. B2: so do source-unvalidated tracks, so a percentile
    is computed only over audio we can point at (cache.excluded_from_aggregates
    is the one shared filter, red-team #8).
    """
    feats = cache.all_features() if feats is None else feats
    twins = cache.excluded_from_aggregates() if twins is None else twins
    ts_map = cache.all_time_signatures()  # promoted column, joined by bridge key
    rows = [{"spotify_track_id": tid, **f} for tid, f in feats.items()
            if tid not in twins
            and all(isinstance(f.get(c), (int, float)) and f.get(c) is not None
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
    out["time_signature"] = out["spotify_track_id"].map(ts_map)  # None where un-estimated

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
    # Percentile honesty: a 0–1 value is a rank WITHIN this population — stamp
    # the population size each row was calibrated against, so a value computed
    # at n=118 is never mistaken for one from a much larger corpus.
    out["population_n"] = len(out)
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
        elif col == "time_signature":
            edges = np.arange(1.5, 8.5, 1.0)     # discrete meters 2..7
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
    if df.empty:
        return 0
    now = datetime.now(timezone.utc)
    # ONE transaction, not one per row (P4.6.4). Was a session+commit per
    # track — the chain's biggest cost and linear in a corpus that keeps
    # growing while the worker's poll interval stays fixed.
    rows = [{"spotify_track_id": row["spotify_track_id"],
             "features": {k: (None if pd.isna(v) else v) for k, v in row.items()
                          if k not in ("spotify_track_id", "version")}}
            for _, row in df.iterrows()]
    version = str(df["version"].iloc[0])
    return cache.upsert_perceptual_many(rows, version=version, computed_at=now)


def catalog_frame() -> pd.DataFrame:
    """The feature catalog as a DataFrame (the /explore picker's source)."""
    return pd.DataFrame(CATALOG)


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    """Write parquet via a temp file + replace — the webapp reads these files
    while the worker rewrites them; a half-written mart must never be served.

    On Windows os.replace raises PermissionError if a reader has the target open
    (a POSIX rename would just succeed), so retry briefly through pandas' short
    read window instead of failing the whole mart rebuild.

    The tmp name is UNIQUE PER PROCESS (Q3 red-team F1): the worker's
    post-drain rebuild and the re-extraction runner's post-batch rebuild can
    fire concurrently — a shared fixed ".tmp" let one process os.replace the
    other's half-written file into place (a truncated mart, served live).
    Unique tmp + atomic replace = last-writer-wins between two COMPLETE files."""
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)  # per-pid tmps must not accumulate
                raise
            time.sleep(0.1)


def build_raw_feature_marts(cache: FeatureCache, marts_dir: Path, *,
                            feats: Optional[dict[str, dict]] = None,
                            excluded: Optional[set[str]] = None) -> dict[str, Any]:
    """The two marts behind `/song/{id}/features` (D-66).

    raw_feature_dictionary — one row per CONCRETE column, expanded from the DSP
      layer's family-level doc. The webapp never restates what a column means;
      it reads this, so retuning an estimator cannot leave the page describing
      the old behaviour (journal #27).
    raw_feature_stats — per-column distribution over the SAME population every
      other surface uses (`excluded_from_aggregates`), so a percentile shown on
      /song agrees with `tempo_pct` on track_card instead of quietly answering
      with a different denominator.
    """
    from ..analysis.clustering import VECTOR_77_COLUMNS
    from ..dsp.feature_doc import RAW_FEATURE_PROMOTED, documented_columns

    # `feats`/`excluded` are passed in by rebuild_marts, which read the same
    # two things moments earlier. Reading them again is the whole 82-column
    # dict for the whole corpus a SECOND time inside the post-drain chain S3a
    # just debounced (director review 2026-07-31) — ~1.9k rows today, linear
    # forever. Standalone callers still get the self-sufficient behaviour.
    feats = cache.all_features() if feats is None else feats
    excluded = cache.excluded_from_aggregates() if excluded is None else excluded
    rows = [f for tid, f in feats.items() if tid not in excluded and f]
    if not rows:
        return {"raw_feature_dictionary": 0, "raw_feature_stats": 0}

    numeric_cols = sorted({k for r in rows for k, v in r.items()
                           if isinstance(v, (int, float))})
    docs = documented_columns(numeric_cols)
    in_vector = set(VECTOR_77_COLUMNS)
    dict_df = pd.DataFrame([{
        "column": c,
        "group": (docs.get(c) or {}).get("group", ""),
        "unit": (docs.get(c) or {}).get("unit", ""),
        "direction": (docs.get(c) or {}).get("direction", ""),
        "description": (docs.get(c) or {}).get("desc", ""),
        "caveat": (docs.get(c) or {}).get("caveat", ""),
        # Which of these actually drive similarity — the honest answer to
        # "so which ones matter?"
        "in_vector_77": c in in_vector,
    } for c in numeric_cols])

    stat_rows = []
    for c in numeric_cols:
        vals = np.array([float(r[c]) for r in rows
                         if isinstance(r.get(c), (int, float))], dtype=float)
        if vals.size == 0:
            continue
        stat_rows.append({
            "column": c, "n": int(vals.size),
            "mean": float(vals.mean()), "std": float(vals.std()),
            "min": float(vals.min()), "p25": float(np.percentile(vals, 25)),
            "p50": float(np.percentile(vals, 50)),
            "p75": float(np.percentile(vals, 75)), "max": float(vals.max()),
        })
    stats_df = pd.DataFrame(stat_rows)

    _write_atomic(dict_df, Path(marts_dir) / "raw_feature_dictionary.parquet")
    _write_atomic(stats_df, Path(marts_dir) / "raw_feature_stats.parquet")
    return {"raw_feature_dictionary": len(dict_df),
            "raw_feature_stats": len(stats_df),
            "promoted_outside_dict": list(RAW_FEATURE_PROMOTED)}


def rebuild_marts(cache: FeatureCache, marts_dir: Path) -> dict[str, Any]:
    """Recompute perceptual-v1 and rewrite all three marts (idempotent).

    THE rebuild entry point: scripts/build_feature_marts.py and the extraction
    worker (post-drain) both call this, so a visitor's freshly-extracted
    tracks reach /explore with no operator step. Percentile-calibrated columns
    recalibrate against the grown population — the version travels on every
    row for exactly this reason. Empty cache → n_tracks 0, nothing written.

    O3a: duplicate flags are refreshed FIRST, so every mart this rebuild
    writes sees the current canonical plane. NOTE: this makes rebuild_marts a
    DB WRITER (track_meta.duplicate_of) — idempotent and last-writer-wins
    under WAL when the worker and the Q3 runner rebuild concurrently.
    """
    cache.refresh_duplicate_flags()
    # ONE corpus read for the whole chain. compute_perceptual and
    # build_raw_feature_marts each used to call `all_features()` themselves —
    # two full 82-column scans of the corpus per post-drain rebuild, the second
    # of them added the same week S3a debounced the first.
    feats = cache.all_features()
    excluded = cache.excluded_from_aggregates()
    df = compute_perceptual(cache, feats=feats, twins=excluded)
    if df.empty:
        return {"n_tracks": 0, "perceptual": df,
                "catalog": pd.DataFrame(), "stats": pd.DataFrame()}
    n = persist_perceptual(cache, df)
    # O3b (red-team #2): the table must match the frame — merge-only persistence
    # would leave a newly-flagged twin's stale row serving /explore + /recommend.
    # B2 widens it to the unvalidated: withholding a track from display while
    # its stale perceptual row still answers /explore is the same trap.
    cache.prune_perceptual(cache.excluded_from_aggregates())
    marts_dir = Path(marts_dir)
    marts_dir.mkdir(parents=True, exist_ok=True)
    catalog = catalog_frame()
    stats = compute_feature_stats(df)
    _write_atomic(df, marts_dir / "track_perceptual.parquet")
    _write_atomic(catalog, marts_dir / "feature_catalog.parquet")
    _write_atomic(stats, marts_dir / "feature_stats.parquet")
    # D-49: the semantic layer rides the same hook + the frame we just computed
    # (no recompute) — the chat's analyst views stay as fresh as /explore.
    raw = build_raw_feature_marts(cache, marts_dir, feats=feats,
                                  excluded=excluded)
    from .semantic import build_semantic_marts
    semantic = build_semantic_marts(cache, df, marts_dir)
    return {"n_tracks": n, "perceptual": df, "catalog": catalog, "stats": stats,
            "semantic": semantic, "raw": raw}
