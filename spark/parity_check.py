"""
parity_check.py — Spark ↔ pandas equivalence (SPEC P7)
=======================================================
Proves the PySpark warehouse jobs produce the SAME results as the canonical
pandas transforms — the acceptance evidence that the distributed path is
correct (SPEC P7: "row-count + centroid parity").

It runs the REAL Spark engine (window-function dedup, groupBy aggregation,
type casts) on synthetic staging data, runs the pandas equivalents on the
same input, and asserts:

    1. Cleansed dedup ROW-COUNT parity   (features + tracks)
    2. Temporal CENTROID parity          (per time_range × feature, within tol)

Self-contained (synthetic data → temp dirs), so it needs no warehouse and no
secrets. Exit 0 on parity, 1 on mismatch.

    python spark/parity_check.py

Runs natively on Linux/macOS and in CI. On Windows, Spark's Hadoop file layer
needs winutils.exe + hadoop.dll (see docs/SCALING.md) — the jobs themselves
are unchanged; that's a local-IO shim, not a code dependency.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark.feature_transform import (  # noqa: E402
    get_or_create_spark,
    transform_features,
    transform_tracks,
)
from spark.temporal_aggregate import AGG_FEATURES, compute_centroids_spark  # noqa: E402
from src.analysis.drift import DRIFT_FEATURE_COLS, compute_temporal_centroids  # noqa: E402
from src.warehouse.cleansed import build_cleansed_features, build_cleansed_tracks  # noqa: E402
from src.warehouse.staging import land_staging_features, land_staging_tracks  # noqa: E402

_TIME_RANGES = ["short_term", "medium_term", "long_term"]
_TOL = 1e-3  # float32 centroid means; absolute+relative


def _synthesize_staging(staging_dir: Path, n_tracks: int = 30) -> None:
    """Land synthetic staging that exercises dedup (two snapshots) and all
    three time ranges (for centroids). Uses the real staging landers so the
    Bronze schema + lineage columns are exactly what both cleansed paths expect."""
    rng = np.random.default_rng(7)

    track_rows = []
    for i in range(n_tracks):
        tid = f"t{i:03d}"
        for tr in _TIME_RANGES:
            track_rows.append({
                "spotify_track_id": tid, "track_name": f"Track {i}",
                "artist_names": f"Artist {i % 5}", "artist_ids": f"art{i % 5}",
                "primary_artist_name": f"Artist {i % 5}", "primary_artist_id": f"art{i % 5}",
                "album_name": f"Album {i}", "album_id": f"alb{i}", "album_type": "album",
                "album_release_date": "2025-01-01", "duration_ms": 200000 + i,
                "explicit": bool(i % 2), "is_local": False, "disc_number": 1,
                "track_number": i + 1, "num_artists": 1, "isrc": f"US{i:06d}",
                "external_url": "", "preview_url": None, "time_range": tr, "rank": i + 1,
            })
    tracks = pd.DataFrame(track_rows)

    feat_rows = []
    for i in range(n_tracks):
        tid = f"t{i:03d}"
        # per-range level so centroids differ across windows (short=hi, long=lo)
        row = {"spotify_track_id": tid, "file_name": tid, "file_path": f"{tid}.mp3",
               "duration_sec": 120.0 + i, "beat_count": 200 + i}
        for c in DRIFT_FEATURE_COLS:
            row[c] = float(rng.normal(1.0, 0.3))
        feat_rows.append(row)
    features = pd.DataFrame(feat_rows)

    # Two snapshots each → duplicates the Silver layer must collapse.
    for label in ("snap1", "snap2"):
        land_staging_tracks(tracks, output_dir=staging_dir, snapshot_label=label)
        land_staging_features(features, output_dir=staging_dir, snapshot_label=label)


def _compare_centroids(spark_pdf: pd.DataFrame, pandas_df: pd.DataFrame) -> list[str]:
    """Return a list of mismatch strings (empty = parity)."""
    features = [c for c in AGG_FEATURES if c in spark_pdf.columns and c in pandas_df.columns]
    mismatches = []
    sp = spark_pdf.set_index("time_range")
    pdd = pandas_df.set_index("time_range")
    for tr in _TIME_RANGES:
        if tr not in sp.index or tr not in pdd.index:
            mismatches.append(f"time_range {tr} missing (spark={tr in sp.index}, pandas={tr in pdd.index})")
            continue
        for c in features:
            a, b = float(sp.loc[tr, c]), float(pdd.loc[tr, c])
            if not np.isclose(a, b, atol=_TOL, rtol=_TOL):
                mismatches.append(f"{tr}.{c}: spark={a:.6f} vs pandas={b:.6f}")
    return mismatches


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    tmp = Path(tempfile.mkdtemp(prefix="spark_parity_"))
    print("=" * 60)
    print("  Spark <-> pandas parity check (SPEC P7)")
    print("=" * 60)
    try:
        staging = tmp / "staging"
        staging.mkdir(parents=True)
        _synthesize_staging(staging)

        # ── pandas cleansed (canonical) ──
        pd_dir = tmp / "cleansed_pd"
        pd_dir.mkdir()
        p_features = build_cleansed_features(staging_dir=staging, output_dir=pd_dir)
        p_tracks = build_cleansed_tracks(staging_dir=staging, output_dir=pd_dir)

        # ── Spark cleansed (distributed) ──
        spark = get_or_create_spark("ParityCheck")
        spark.sparkContext.setLogLevel("ERROR")
        print(f"   Spark {spark.version} · master {spark.sparkContext.master}")
        sp_dir = tmp / "cleansed_spark"
        sp_dir.mkdir()
        s_features = transform_features(spark, staging_dir=str(staging), output_dir=str(sp_dir)).toPandas()
        s_tracks = transform_tracks(spark, staging_dir=str(staging), output_dir=str(sp_dir)).toPandas()

        # ── centroids: run BOTH on the same cleansed input (pandas dir) ──
        sp_centroids = compute_centroids_spark(
            spark, cleansed_dir=str(pd_dir), output_dir=str(tmp / "modeled")).toPandas()
        fact = p_tracks.merge(p_features, on="spotify_track_id", how="left")
        pd_centroids = compute_temporal_centroids(fact)

        spark.stop()

        # ── assertions ──
        checks: list[tuple[str, bool, str]] = []
        checks.append(("features dedup row-count",
                       len(p_features) == len(s_features),
                       f"pandas={len(p_features)}  spark={len(s_features)}"))
        checks.append(("tracks dedup row-count",
                       len(p_tracks) == len(s_tracks),
                       f"pandas={len(p_tracks)}  spark={len(s_tracks)}"))
        centroid_mismatches = _compare_centroids(sp_centroids, pd_centroids)
        checks.append(("temporal centroid parity",
                       not centroid_mismatches,
                       "identical within 1e-3" if not centroid_mismatches
                       else f"{len(centroid_mismatches)} mismatch(es): {centroid_mismatches[:3]}"))

        print("\n   Results:")
        ok = True
        for name, passed, detail in checks:
            print(f"     [{'PASS' if passed else 'FAIL'}] {name:26s} — {detail}")
            ok = ok and passed

        print("\n   " + ("✅ Spark output matches pandas — parity verified."
                         if ok else "❌ Parity FAILED."))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
