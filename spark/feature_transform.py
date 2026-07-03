"""
feature_transform.py — PySpark Feature Transformation Job
===========================================================
Transforms raw DSP features from Staging into the Cleansed layer
using PySpark for distributed processing.

Why PySpark Here (Not Pandas)?
    In production, DSP feature extraction produces millions of rows
    (one per track × one per extraction run). The deduplication,
    type casting, and null handling operations that the Cleansed
    layer requires are exactly the kind of embarrassingly parallel
    transforms that Spark excels at.

    This job is designed to run identically on:
    - Local mode: SparkSession.builder.master("local[*]")
    - Cluster mode: spark-submit --master yarn/k8s

Execution:
    spark-submit spark/feature_transform.py \\
        --staging-dir data/staging \\
        --output-dir data/cleansed

Local Testing:
    python spark/feature_transform.py  # uses local[*] by default

Partitioning Strategy:
    - Input: Read all features_raw_*.parquet from staging (coalesce on read)
    - Processing: No repartition needed — dedup is a single shuffle on spotify_track_id
    - Output: Single Parquet file (small dataset); partition by time_range for large ones

Time Complexity: O(n log n) for the sort + dedup
Space Complexity: O(n) — single pass after sort, no materialization of intermediate DFs
"""

import sys
from pathlib import Path
from typing import Optional

# ── PySpark imports ──
try:
    from pyspark.sql import SparkSession, DataFrame
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        StructType, StructField, StringType, FloatType,
        IntegerType, BooleanType,
    )
    from pyspark.sql.window import Window
except ImportError:
    raise ImportError(
        "PySpark is required for this job.\n"
        "Install: pip install pyspark>=3.5.0\n"
        "Or run the pandas-based equivalent in src/warehouse/cleansed.py"
    )

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = _PROJECT_ROOT / "data" / "warehouse" / "staging"
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"


def get_or_create_spark(app_name: str = "TemporalAudioPipeline") -> SparkSession:
    """
    Get or create a SparkSession.

    In local mode, uses all available cores. In cluster mode,
    the cluster manager provides the SparkSession configuration.

    Memory config:
        driver.memory=2g is sufficient for our dataset size (<100K tracks).
        For production (>1M tracks), increase to 8g+ and add executor config.
    """
    return (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )


def transform_features(
    spark: SparkSession,
    staging_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> DataFrame:
    """
    Transform raw DSP features from Staging → Cleansed using PySpark.

    Processing steps (mirrors src/warehouse/cleansed.py logic):
        1. Read all features_raw_*.parquet from Staging
        2. Deduplicate by spotify_track_id (keep latest by _landed_at)
        3. Cast all numeric columns to FloatType
        4. Fill nulls: numerics → 0.0, strings → "unknown"
        5. Drop lineage columns
        6. Write to cleansed_features_spark.parquet

    Args:
        spark:       Active SparkSession.
        staging_dir: Path to Staging directory.
        output_dir:  Path to Cleansed output directory.

    Returns:
        Cleansed Spark DataFrame.

    Scale Mechanics:
        - Read: Parquet pushdown predicate on file glob → only reads feature files
        - Dedup: Window function with row_number() → single shuffle on spotify_track_id
        - Cast: Column-level map → no shuffle, fully parallelized
        - Write: coalesce(1) for small datasets; repartition(N) for production
    """
    staging_path = str(staging_dir or STAGING_DIR)
    output_path = str(output_dir or CLEANSED_DIR)

    # ── Step 1: Read staging data ──
    features_glob = f"{staging_path}/features_raw_*.parquet"
    print(f"   📂 Reading from: {features_glob}")

    try:
        df = spark.read.parquet(features_glob)
    except Exception as e:
        print(f"   ⚠️  No staging feature files found: {e}")
        return spark.createDataFrame([], schema=StructType())

    total_rows = df.count()
    print(f"   📊 Raw rows: {total_rows}")

    # ── Step 2: Deduplicate ──
    # Window function: partition by track_id, order by landed_at desc → keep row 1
    if "_landed_at" in df.columns:
        window = Window.partitionBy("spotify_track_id").orderBy(F.col("_landed_at").desc())
        df = df.withColumn("_row_num", F.row_number().over(window))
        df = df.filter(F.col("_row_num") == 1).drop("_row_num")

        deduped_rows = df.count()
        print(f"   🔄 After dedup: {deduped_rows} rows (removed {total_rows - deduped_rows})")
    else:
        df = df.dropDuplicates(["spotify_track_id"])

    # ── Step 3: Type enforcement ──
    # Identify numeric columns and cast to FloatType
    string_cols = {"spotify_track_id", "file_name", "file_path", "estimated_mode"}
    int_cols = {"beat_count", "estimated_key"}

    for field in df.schema.fields:
        col_name = field.name
        if col_name.startswith("_"):
            continue
        if col_name in string_cols:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit("unknown")).cast(StringType()))
        elif col_name in int_cols:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name).cast(IntegerType()), F.lit(0)))
        elif field.dataType in (FloatType(), ) or "float" in str(field.dataType).lower() or "double" in str(field.dataType).lower():
            df = df.withColumn(col_name, F.coalesce(F.col(col_name).cast(FloatType()), F.lit(0.0)))

    # ── Step 4: Drop lineage columns ──
    lineage_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(*lineage_cols)

    # ── Step 5: Write ──
    output_file = f"{output_path}/cleansed_features_spark.parquet"
    df.coalesce(1).write.mode("overwrite").parquet(output_file)

    final_count = df.count()
    print(f"   ✅ Cleansed features (Spark): {final_count} rows → cleansed_features_spark.parquet")

    return df


def transform_tracks(
    spark: SparkSession,
    staging_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> DataFrame:
    """
    Transform raw track metadata from Staging → Cleansed using PySpark.

    Similar to transform_features but handles tracks with time_range:
        - Dedup grain: (spotify_track_id, time_range)
        - Type enforcement on metadata columns
        - Boolean casting for explicit/is_local

    Args:
        spark:       Active SparkSession.
        staging_dir: Path to Staging directory.
        output_dir:  Path to Cleansed output directory.

    Returns:
        Cleansed Spark DataFrame.
    """
    staging_path = str(staging_dir or STAGING_DIR)
    output_path = str(output_dir or CLEANSED_DIR)

    tracks_glob = f"{staging_path}/tracks_raw_*.parquet"
    print(f"   📂 Reading from: {tracks_glob}")

    try:
        df = spark.read.parquet(tracks_glob)
    except Exception:
        print("   ⚠️  No staging track files found")
        return spark.createDataFrame([], schema=StructType())

    total_rows = df.count()
    print(f"   📊 Raw rows: {total_rows}")

    # ── Dedup by (track_id, time_range) ──
    dedup_cols = ["spotify_track_id", "time_range"] if "time_range" in df.columns else ["spotify_track_id"]

    if "_landed_at" in df.columns:
        window = Window.partitionBy(*dedup_cols).orderBy(F.col("_landed_at").desc())
        df = df.withColumn("_row_num", F.row_number().over(window))
        df = df.filter(F.col("_row_num") == 1).drop("_row_num")
    else:
        df = df.dropDuplicates(dedup_cols)

    # ── Type enforcement ──
    string_cols = {
        "spotify_track_id", "track_name", "artist_names", "artist_ids",
        "primary_artist_name", "primary_artist_id", "album_name", "album_id",
        "album_type", "album_release_date", "time_range", "isrc",
        "external_url", "preview_url",
    }
    bool_cols = {"explicit", "is_local"}
    int_cols = {"duration_ms", "disc_number", "track_number", "num_artists", "rank"}

    for col_name in df.columns:
        if col_name.startswith("_"):
            continue
        if col_name in string_cols:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name).cast(StringType()), F.lit("unknown")))
        elif col_name in bool_cols:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name).cast(BooleanType()), F.lit(False)))
        elif col_name in int_cols:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name).cast(IntegerType()), F.lit(0)))

    # ── Drop lineage ──
    lineage_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(*lineage_cols)

    # ── Write ──
    output_file = f"{output_path}/cleansed_tracks_spark.parquet"
    df.coalesce(1).write.mode("overwrite").parquet(output_file)

    final_count = df.count()
    print(f"   ✅ Cleansed tracks (Spark): {final_count} rows → cleansed_tracks_spark.parquet")

    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("=" * 60)
    print("  🔧 PySpark Feature Transform — Staging → Cleansed")
    print("=" * 60)

    spark = get_or_create_spark()
    print(f"   Spark version: {spark.version}")
    print(f"   Master: {spark.sparkContext.master}")
    print()

    transform_features(spark)
    print()
    transform_tracks(spark)

    spark.stop()
    print("\n   ✅ Transform complete.")
