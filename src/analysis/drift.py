"""
drift.py — Taste Drift Analysis Engine
========================================
Computes quantitative metrics for how a user's musical taste evolves
across Spotify's three temporal windows.

Core Metrics:
    1. Taste Drift Score: RMS σ-shift between standardized temporal centroids
    2. Temporal Centroids: Mean feature vector per time range (raw units)
    3. Feature Deltas: Per-feature change between time ranges
    4. Stability Score: How consistent taste is across all windows

Why RMS σ-shift (ADR-003 amended 2026-07-03)?
    Audio features span wildly different scales (tempo 60-200 vs RMS 0-1), so
    scale-invariance is mandatory — ADR-003 originally chose cosine for that.
    Measured against real data, cosine failed twice: on RAW centroids the
    angle is dominated by the largest features (score ≈ 0.0000 always); on
    CENTERED z-centroids the per-range means must sum to ~0, forcing ~120°
    angles (score ≈ 1.5 always). Both are artifacts of measuring DIRECTION
    only. The fix keeps the scale-invariance (per-feature z-scoring) and
    measures MAGNITUDE: RMS per-feature shift in σ units — a multivariate
    effect size (0 = identical; ~0.2 = subtle; 1.0 = every feature moved a
    full standard deviation). See engineering journal #10.

Scale Mechanics (PySpark):
    In a distributed environment, centroids are computed via:
        df.groupBy("time_range").agg({col: "mean" for col in feature_cols})
    This is a single-pass aggregation with shuffle only on time_range (3 partitions).
    O(n) time, O(k × d) memory where k=3 time ranges and d=77 features.

Reference: Taste Drift analysis architecture
"""

from typing import Optional, Union
from pathlib import Path

import numpy as np
import pandas as pd

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"

# ── Feature columns used for drift computation ──
# These are the numeric DSP columns that constitute the acoustic profile.
# Excludes identifiers, metadata, and non-acoustic columns.
DRIFT_FEATURE_COLS = [
    # Rhythm (4)
    "tempo_bpm", "onset_strength_mean", "onset_strength_std", "beats_per_sec",
    # Energy (4)
    "rms_mean", "rms_std", "zcr_mean", "zcr_std",
    # Spectral shape (4)
    "spectral_centroid_mean", "spectral_centroid_std",
    "spectral_rolloff_mean", "spectral_rolloff_std",
    # Acousticness proxy (1)
    "harmonic_ratio",
]

# Extended feature columns including MFCCs and chroma
DRIFT_FEATURE_COLS_EXTENDED = DRIFT_FEATURE_COLS + [
    f"mfcc_mean_{i}" for i in range(13)
] + [
    f"chroma_mean_{note}" for note in ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
]

# Human-readable labels for key features (used in visualizations)
FEATURE_LABELS = {
    "tempo_bpm": "Tempo (BPM)",
    "rms_mean": "Energy",
    "zcr_mean": "Noisiness",
    "zcr_std": "Noisiness Variability",
    "spectral_centroid_mean": "Brightness",
    "spectral_centroid_std": "Brightness Variability",
    "spectral_rolloff_mean": "Freq. Ceiling",
    "spectral_rolloff_std": "Freq. Ceiling Variability",
    "harmonic_ratio": "Acousticness",
    "onset_strength_mean": "Rhythmic Activity",
    "onset_strength_std": "Rhythm Variability",
    "beats_per_sec": "Beat Density",
    "rms_std": "Dynamic Range",
}


def compute_temporal_centroids(
    fact_df: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Compute the acoustic centroid (mean feature vector) per time range.

    The centroid represents the "average sound" of the user's listening
    for a given time window. Comparing centroids across windows reveals
    how taste shifts over time.

    Args:
        fact_df:       fact_listening_features DataFrame.
        feature_cols:  Which feature columns to include. Defaults to DRIFT_FEATURE_COLS.

    Returns:
        DataFrame with one row per time_range and columns for each feature mean.
        Shape: (3, len(feature_cols) + 1) — the +1 is the time_range column.

    Example output:
        time_range      tempo_bpm   rms_mean   harmonic_ratio  ...
        short_term      128.5       0.32       0.71           ...
        medium_term     122.1       0.28       0.75           ...
        long_term       118.9       0.25       0.78           ...
    """
    if feature_cols is None:
        feature_cols = DRIFT_FEATURE_COLS

    if "time_range" not in fact_df.columns:
        raise ValueError("fact_df must contain 'time_range' column")

    # Filter to available features
    available = [c for c in feature_cols if c in fact_df.columns]
    if not available:
        raise ValueError(f"No feature columns found. Expected: {feature_cols[:5]}...")

    centroids = fact_df.groupby("time_range")[available].mean().reset_index()

    # Sort by temporal order
    time_order = {"short_term": 0, "medium_term": 1, "long_term": 2}
    centroids["_sort"] = centroids["time_range"].map(time_order)
    centroids = centroids.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

    print(f"   📊 Computed centroids for {len(centroids)} time ranges × {len(available)} features")

    return centroids


def compute_taste_drift(
    fact_df: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
) -> dict:
    """
    Compute the Taste Drift Score and related metrics.

    The Taste Drift Score is the RMS σ-shift between the short-term and
    long-term standardized acoustic centroids: "on average, each acoustic
    feature moved X standard deviations between recent and all-time
    listening." A multivariate effect size — scale-invariant via per-feature
    z-scoring (ADR-003's intent), zero for identical distributions.

    Drift Score interpretation (σ units, effect-size bands):
        0.00 – 0.15: Minimal drift (stable taste, comfort zone)
        0.15 – 0.35: Moderate drift (some exploration)
        0.35 – 0.60: Significant drift (active taste evolution)
        0.60+:       Major drift (genre shift or new discovery phase)

    Returns:
        Dict with:
            - drift_score: float (RMS σ-shift, 0 = identical; unbounded above)
            - drift_label: str (human-readable interpretation)
            - centroids: DataFrame of centroids per time range
            - pairwise_distances: dict of all pairwise cosine distances
            - stability_score: float (inverse of average pairwise distance)
            - feature_deltas: DataFrame of per-feature changes
    """
    if feature_cols is None:
        feature_cols = DRIFT_FEATURE_COLS

    centroids = compute_temporal_centroids(fact_df, feature_cols)
    available = [c for c in feature_cols if c in centroids.columns]

    # ── Standardize BEFORE the distance math ──
    # Raw feature scales differ by orders of magnitude (spectral_rolloff
    # ~8000 Hz vs rms_mean ~0.1), so cosine on raw centroids is dominated by
    # the few largest columns and reads ≈0.0000 on any real corpus — the
    # angle barely moves even when many features shift by 5-10%. Z-scoring
    # each feature across the corpus first makes every feature contribute
    # equally to the angle (this is ADR-003's scale-invariance intent,
    # applied correctly). Raw centroids are still returned for visuals and
    # per-feature deltas.
    z = fact_df[["time_range"] + available].copy()
    for col in available:
        std = float(fact_df[col].std())
        if std > 1e-12:
            z[col] = (fact_df[col] - float(fact_df[col].mean())) / std
        else:
            z[col] = 0.0
    z_centroids = z.groupby("time_range")[available].mean()

    # Extract standardized centroid vectors for distance computation
    centroid_vectors = {}
    for tr, row in z_centroids.iterrows():
        centroid_vectors[tr] = row.values.astype(np.float32)

    # ── Pairwise drift: RMS σ-shift between standardized centroids ──
    # Why not cosine here? Cosine on RAW centroids is dominated by the
    # largest-scale features (reads ≈0 always); cosine on CENTERED z-centroids
    # has the opposite artifact — the per-range centroids of z-scores must
    # sum to ~0, forcing near-120° angles (distance ≈1.5) for ANY corpus,
    # noise included. Direction-only metrics can't express effect SIZE here.
    # RMS σ-shift = sqrt(mean_j (Δz_j)²): "on average, each acoustic feature
    # moved X standard deviations between the two windows." Scale-invariant
    # (via z-scoring — ADR-003's intent), zero for identical distributions,
    # and an honest multivariate effect size.
    pairs = [
        ("short_term", "medium_term"),
        ("medium_term", "long_term"),
        ("short_term", "long_term"),
    ]

    pairwise = {}
    for tr_a, tr_b in pairs:
        if tr_a in centroid_vectors and tr_b in centroid_vectors:
            diff = centroid_vectors[tr_a] - centroid_vectors[tr_b]
            pairwise[f"{tr_a}_vs_{tr_b}"] = float(np.sqrt(np.mean(diff ** 2)))

    # ── Primary drift score: short_term vs long_term ──
    drift_score = pairwise.get("short_term_vs_long_term", 0.0)

    # ── Drift label (effect-size bands, in σ units) ──
    if drift_score < 0.15:
        drift_label = "Minimal Drift — Your taste is remarkably stable"
    elif drift_score < 0.35:
        drift_label = "Moderate Drift — You're exploring new sounds"
    elif drift_score < 0.60:
        drift_label = "Significant Drift — Your taste is actively evolving"
    else:
        drift_label = "Major Drift — You're in a musical discovery phase"

    # ── Stability score (inverse of mean pairwise distance) ──
    if pairwise:
        avg_dist = np.mean(list(pairwise.values()))
        stability = 1.0 - min(avg_dist, 1.0)
    else:
        stability = 1.0

    # ── Feature deltas ──
    deltas = compute_feature_deltas(centroids, available)

    # ── Report ──
    print(f"\n   🎯 Taste Drift Analysis:")
    print(f"      Drift Score: {drift_score:.4f}")
    print(f"      Assessment:  {drift_label}")
    print(f"      Stability:   {stability:.4f}")
    print(f"\n   📐 Pairwise Distances:")
    for pair, dist in pairwise.items():
        print(f"      {pair}: {dist:.4f}")

    return {
        "drift_score": drift_score,
        "drift_label": drift_label,
        "centroids": centroids,
        "pairwise_distances": pairwise,
        "stability_score": stability,
        "feature_deltas": deltas,
    }


def compute_feature_deltas(
    centroids: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Compute per-feature deltas between time ranges.

    For each feature, computes:
        - absolute_delta: |short_term_value - long_term_value|
        - relative_delta: delta as % of long_term value
        - direction: "increasing", "decreasing", or "stable"

    This tells you WHICH features are driving the drift.
    E.g., "Your tempo has increased 15% in the short term — you're
    listening to faster music recently."

    Args:
        centroids:     Centroids DataFrame from compute_temporal_centroids().
        feature_cols:  Feature columns to analyze.

    Returns:
        DataFrame with one row per feature, sorted by absolute_delta descending.
    """
    if feature_cols is None:
        feature_cols = [c for c in centroids.columns if c != "time_range"]

    available = [c for c in feature_cols if c in centroids.columns]

    # Get short and long-term centroid rows
    short = centroids[centroids["time_range"] == "short_term"]
    long = centroids[centroids["time_range"] == "long_term"]

    if short.empty or long.empty:
        print("   ⚠️  Need both short_term and long_term data for deltas")
        return pd.DataFrame()

    records = []
    for col in available:
        short_val = float(short[col].iloc[0])
        long_val = float(long[col].iloc[0])
        abs_delta = abs(short_val - long_val)
        rel_delta = abs_delta / max(abs(long_val), 1e-8)

        if short_val > long_val * 1.02:
            direction = "increasing"
        elif short_val < long_val * 0.98:
            direction = "decreasing"
        else:
            direction = "stable"

        records.append({
            "feature": col,
            "label": FEATURE_LABELS.get(col, col),
            "short_term": round(short_val, 4),
            "long_term": round(long_val, 4),
            "absolute_delta": round(abs_delta, 4),
            "relative_delta_pct": round(rel_delta * 100, 2),
            "direction": direction,
        })

    df = pd.DataFrame(records).sort_values("absolute_delta", ascending=False).reset_index(drop=True)

    # Report top movers
    print(f"\n   📊 Top Feature Changes (short_term vs long_term):")
    for _, row in df.head(5).iterrows():
        arrow = "↑" if row["direction"] == "increasing" else ("↓" if row["direction"] == "decreasing" else "→")
        print(f"      {arrow} {row['label']}: {row['relative_delta_pct']:.1f}% ({row['direction']})")

    return df


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine distance between two vectors.

    cosine_distance = 1 - cosine_similarity
    Range: [0, 2] where 0 = identical direction, 1 = orthogonal, 2 = opposite.

    For taste drift, we expect values in [0, 0.5] — similar but not identical.
    """
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a < 1e-8 and norm_b < 1e-8:
        return 0.0  # Both ~zero (e.g. z-centroids of a range-uniform corpus) → no drift
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 1.0  # One-sided degenerate → undefined, treat as max distance

    similarity = dot / (norm_a * norm_b)
    # Clamp to [-1, 1] for numerical stability
    similarity = np.clip(similarity, -1.0, 1.0)
    return float(1.0 - similarity)
