"""Known-answer Spark check — a session that STARTS proves nothing.

Why this exists alongside `parity_check.py`: parity compares Spark to pandas,
so if the Python worker boundary were subtly broken in the same way on both
sides, parity could still agree. This file instead compares Spark to
HAND-COMPUTED CONSTANTS, and deliberately exercises the two things that break
first on a fresh host:

  1. a shuffle (groupBy) — the distributed path,
  2. a Python UDF — the first thing that crosses driver -> worker Python, and
     the first casualty of a PYSPARK_PYTHON pointing at the wrong interpreter
     (journal #62's Anaconda shadow was exactly this class).

It also reports, without asserting, whether this host can WRITE local files —
Hadoop's RawLocalFileSystem shells out to winutils.exe on Windows, so reads
work and writes do not. Our transforms DO write parquet
(`feature_transform.py`, `temporal_aggregate.py`), which is precisely why the
Spark path is WSL-only here.

Run:  powershell -File scripts\spark_wsl.ps1 spark/known_answer_check.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# ── the fixture: 6 rows, values chosen so every expected number is trivial ──
ROWS = [
    ("a", 1),
    ("a", 2),
    ("a", 3),
    ("b", 10),
    ("b", 20),
    ("c", 100),
]

# Hand-computed, not derived from the code under test.
EXPECTED_GROUP_SUMS = {"a": 6, "b": 30, "c": 100}
EXPECTED_GROUP_COUNTS = {"a": 3, "b": 2, "c": 1}
EXPECTED_TOTAL = 136
EXPECTED_UDF_SUM = 136 * 2  # udf doubles every value


def main() -> int:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import IntegerType

    failures: list[str] = []
    notes: list[str] = []

    spark = (
        SparkSession.builder.appName("known-answer")
        .master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    print(f"   Spark {spark.version} | python {sys.version.split()[0]}")
    print(f"   driver={os.environ.get('PYSPARK_DRIVER_PYTHON', '(unset)')}")
    print(f"   worker={os.environ.get('PYSPARK_PYTHON', '(unset)')}")

    df = spark.createDataFrame(ROWS, ["k", "v"])

    # ── 1. groupBy (the shuffle) ────────────────────────────────────────────
    got_sums = {r["k"]: r["s"] for r in df.groupBy("k").agg(F.sum("v").alias("s")).collect()}
    got_counts = {r["k"]: r["c"] for r in df.groupBy("k").agg(F.count("v").alias("c")).collect()}
    if got_sums != EXPECTED_GROUP_SUMS:
        failures.append(f"group sums {got_sums} != {EXPECTED_GROUP_SUMS}")
    if got_counts != EXPECTED_GROUP_COUNTS:
        failures.append(f"group counts {got_counts} != {EXPECTED_GROUP_COUNTS}")

    total = df.agg(F.sum("v")).collect()[0][0]
    if total != EXPECTED_TOTAL:
        failures.append(f"total {total} != {EXPECTED_TOTAL}")

    # ── 2. Python UDF (the driver -> worker boundary) ───────────────────────
    double = F.udf(lambda x: None if x is None else int(x) * 2, IntegerType())
    udf_sum = df.withColumn("d", double(F.col("v"))).agg(F.sum("d")).collect()[0][0]
    if udf_sum != EXPECTED_UDF_SUM:
        failures.append(f"udf sum {udf_sum} != {EXPECTED_UDF_SUM}")

    # UDF over a shuffle — the combination, not just each half.
    udf_group = {
        r["k"]: r["s"]
        for r in df.withColumn("d", double(F.col("v")))
        .groupBy("k")
        .agg(F.sum("d").alias("s"))
        .collect()
    }
    expected_udf_group = {k: v * 2 for k, v in EXPECTED_GROUP_SUMS.items()}
    if udf_group != expected_udf_group:
        failures.append(f"udf+group {udf_group} != {expected_udf_group}")

    # ── 3. local WRITE capability (reported, not asserted) ──────────────────
    # Our transforms write parquet; on Windows this needs winutils.exe, which
    # this machine deliberately no longer has.
    tmp = tempfile.mkdtemp(prefix="spark_known_answer_")
    out = os.path.join(tmp, "roundtrip.parquet")
    try:
        df.coalesce(1).write.mode("overwrite").parquet(out)
        n = spark.read.parquet(out).count()
        if n != len(ROWS):
            failures.append(f"parquet round-trip returned {n} rows, expected {len(ROWS)}")
        else:
            notes.append(f"local parquet write+read OK ({n} rows)")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"local parquet write FAILED: {type(exc).__name__}: {str(exc)[:200]}")

    spark.stop()

    print("\n   Results:")
    for n in notes:
        print(f"     [note] {n}")
    if failures:
        for f in failures:
            print(f"     [FAIL] {f}")
        print("\n   Known-answer check FAILED.")
        return 1
    print("     [PASS] groupBy sums + counts match hand-computed constants")
    print("     [PASS] total matches")
    print("     [PASS] Python UDF crosses the worker boundary correctly")
    print("     [PASS] UDF over a shuffle matches")
    print("\n   Known-answer check PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
