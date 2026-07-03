"""
temporal_aggregate.py — PySpark Temporal Aggregation Job
=========================================================
Computes temporal aggregates from the Cleansed layer:
    - Acoustic centroids per time range
    - Pairwise cosine distances between centroids
    - Per-feature variance analysis

This is the distributed version of src/analysis/drift.py.
In production, this would run as a scheduled Dataflow/Spark job
to recompute drift metrics as new listening data arrives.

Execution:
    spark-submit spark/temporal_aggregate.py
    python spark/temporal_aggregate.py  # local mode

Partitioning Strategy:
    - groupBy("time_range") produces exactly 3 groups → 3 partitions
    - Each partition computes a mean vector independently (embarrassingly parallel)
    - Final pairwise distances computed on the driver (3×3 matrix = trivial)

Time Complexity: O(n) single-pass aggregation
Space Complexity: O(d) per partition where d = 77 features
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from pyspark.sql import SparkSession, DataFrame
    from pyspark.sql import functions as F
    from pyspark.sql.types import StructType, StructField, StringType, FloatType
except ImportError:
    raise ImportError(
        "PySpark is required. Install: pip install pyspark>=3.5.0"
    )

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"

# ── Feature columns for aggregation ──
AGG_FEATURES = [
    "tempo_bpm", "onset_strength_mean", "onset_strength_std", "beats_per_sec",
    "rms_mean", "rms_std", "zcr_mean", "zcr_std",
    "spectral_centroid_mean", "spectral_centroid_std",
    "spectral_rolloff_mean", "spectral_rolloff_std",
    "harmonic_ratio",
]


def compute_centroids_spark(
    spark: SparkSession,
    cleansed_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> DataFrame:
    """
    Compute acoustic centroids per time range using PySpark.

    This is the distributed equivalent of:
        fact_df.groupby("time_range")[features].mean()

    In Spark, this is a single-stage aggregation with shuffle
    only on time_range (3 partitions) — extremely efficient.

    The output is a wide DataFrame: one row per time_range,
    one column per feature containing the mean value.

    Args:
        spark:        Active SparkSession.
        cleansed_dir: Path to Cleansed directory.
        output_dir:   Path to Modeled output directory.

    Returns:
        Spark DataFrame with centroids.
    """
    cleansed_path = str(cleansed_dir or CLEANSED_DIR)
    output_path = str(output_dir or MODELED_DIR)

    # ── Load cleansed fact data ──
    # We need both tracks (for time_range) and features (for DSP columns)
    tracks_path = f"{cleansed_path}/cleansed_tracks.parquet"
    features_path = f"{cleansed_path}/cleansed_features.parquet"

    try:
        tracks_df = spark.read.parquet(tracks_path)
        features_df = spark.read.parquet(features_path)
    except Exception as e:
        print(f"   ⚠️  Could not load cleansed data: {e}")
        return spark.createDataFrame([], schema=StructType())

    # ── Join tracks with features ──
    fact_df = tracks_df.join(features_df, on="spotify_track_id", how="left")

    # ── Compute centroids ──
    available = [c for c in AGG_FEATURES if c in fact_df.columns]
    if not available:
        print("   ⚠️  No feature columns found for aggregation")
        return spark.createDataFrame([], schema=StructType())

    # Build aggregation expressions: mean of each feature per time_range
    agg_exprs = [
        F.mean(F.col(c)).alias(c) for c in available
    ]
    # Also compute count and std for richness
    agg_exprs.append(F.count("*").alias("track_count"))
    for c in available:
        agg_exprs.append(F.stddev(F.col(c)).alias(f"{c}_std_within"))

    centroids = fact_df.groupBy("time_range").agg(*agg_exprs)

    # ── Write ──
    centroids_path = f"{output_path}/temporal_centroids_spark.parquet"
    centroids.coalesce(1).write.mode("overwrite").parquet(centroids_path)

    print(f"   ✅ Temporal centroids computed:")
    centroids.select("time_range", "track_count", *available[:5]).show(truncate=False)

    return centroids


def compute_drift_metrics_spark(
    spark: SparkSession,
    cleansed_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """
    Compute taste drift metrics using PySpark.

    Steps:
        1. Compute centroids (distributed aggregation)
        2. Collect to driver (3 rows — trivial)
        3. Compute pairwise cosine distances on driver

    Why collect to driver?
        Pairwise distance between 3 vectors is O(1) work.
        Distributing this would add unnecessary shuffle overhead.
        The PySpark value here is in the AGGREGATION (step 1),
        not the distance computation (step 3).

    Returns:
        Dict with drift_score, pairwise_distances, centroids_pdf
    """
    centroids_df = compute_centroids_spark(spark, cleansed_dir, output_dir)

    if centroids_df.rdd.isEmpty():
        return {"drift_score": 0.0, "error": "No data"}

    # Collect to driver for distance computation
    centroids_pdf = centroids_df.toPandas()

    available = [c for c in AGG_FEATURES if c in centroids_pdf.columns]

    # Extract vectors per time range
    vectors = {}
    for _, row in centroids_pdf.iterrows():
        tr = row["time_range"]
        vec = row[available].values.astype(np.float32)
        vectors[tr] = vec

    # Compute pairwise cosine distances
    pairwise = {}
    pairs = [
        ("short_term", "medium_term"),
        ("medium_term", "long_term"),
        ("short_term", "long_term"),
    ]

    for tr_a, tr_b in pairs:
        if tr_a in vectors and tr_b in vectors:
            a, b = vectors[tr_a], vectors[tr_b]
            dot = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a > 1e-8 and norm_b > 1e-8:
                sim = dot / (norm_a * norm_b)
                sim = np.clip(sim, -1.0, 1.0)
                dist = float(1.0 - sim)
            else:
                dist = 1.0
            pairwise[f"{tr_a}_vs_{tr_b}"] = dist

    drift_score = pairwise.get("short_term_vs_long_term", 0.0)

    print(f"\n   🎯 Taste Drift Score (Spark): {drift_score:.4f}")
    for pair, dist in pairwise.items():
        print(f"      {pair}: {dist:.4f}")

    return {
        "drift_score": drift_score,
        "pairwise_distances": pairwise,
        "centroids_pdf": centroids_pdf,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    from feature_transform import get_or_create_spark

    print("=" * 60)
    print("  📊 PySpark Temporal Aggregation — Drift Metrics")
    print("=" * 60)

    spark = get_or_create_spark("TemporalAggregate")
    print(f"   Spark version: {spark.version}")
    print()

    metrics = compute_drift_metrics_spark(spark)

    spark.stop()
    print("\n   ✅ Aggregation complete.")
