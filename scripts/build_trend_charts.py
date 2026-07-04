"""
build_trend_charts.py — SPEC P3: temporal trend visuals (one command → 4 PNGs)
===============================================================================
Wires the existing dark-theme plotters (src/analysis/visualizations.py) to the
real gold layer and exports deterministic PNGs for the README and P4's static
report:

    artifacts/drift_radar.png            acoustic profile polygons per window
    artifacts/temporal_heatmap.png       feature × time-range intensity
    artifacts/feature_distributions.png  box plots (distribution vs outliers)
    artifacts/artist_flow.png            top artists per window

    python scripts/build_trend_charts.py

Deliberately NOT included: plot_umap_by_time_range — it recomputes UMAP on
raw unscaled features (the scale-domination artifact of journal #10), and a
track appearing in multiple windows would plot identical overlapping points.
`artifacts/taste_map.png` (SPEC P1) is the canonical projection.
"""

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — we only save files
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODELED_DIR = PROJECT_ROOT / "data" / "warehouse" / "modeled"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s — %(message)s")

# Radar axes: the most interpretable subset (13 axes is unreadable; ~8 is the
# sweet spot per the plotter's own guidance).
RADAR_FEATURES = [
    "tempo_bpm", "rms_mean", "rms_std", "zcr_mean",
    "spectral_centroid_mean", "spectral_rolloff_mean",
    "harmonic_ratio", "onset_strength_mean",
]


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    from src.analysis.drift import compute_temporal_centroids
    from src.analysis.visualizations import (
        plot_drift_radar,
        plot_feature_distributions,
        plot_genre_flow,
        plot_temporal_heatmap,
    )

    print("=" * 60)
    print("  📈 Temporal trend charts (SPEC P3)")
    print("=" * 60)

    fact_path = MODELED_DIR / "fact_listening_features.parquet"
    if not fact_path.exists():
        print("❌ Fact table not found — run the pipeline first.")
        sys.exit(1)

    fact = pd.read_parquet(fact_path, engine="pyarrow")
    if "rms_mean" not in fact.columns:
        print("❌ Fact table has no DSP features — rerun without --skip-extract.")
        sys.exit(1)

    centroids = compute_temporal_centroids(fact)

    # σ-shift normalization stats (per-feature mean/std over TRACKS) so radar
    # and heatmap divergence means effect size — same units as the drift
    # score, not min-max theater (journal #10).
    from src.analysis.drift import DRIFT_FEATURE_COLS
    stat_cols = [c for c in DRIFT_FEATURE_COLS if c in fact.columns]
    corpus_stats = (fact[stat_cols].mean(), fact[stat_cols].std())

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    charts = [
        ("drift_radar.png",
         lambda p: plot_drift_radar(centroids, feature_cols=RADAR_FEATURES,
                                    corpus_stats=corpus_stats, save_path=p)),
        ("temporal_heatmap.png",
         lambda p: plot_temporal_heatmap(centroids, corpus_stats=corpus_stats,
                                         save_path=p)),
        ("feature_distributions.png",
         lambda p: plot_feature_distributions(fact, save_path=p)),
        ("artist_flow.png",
         lambda p: plot_genre_flow(fact, save_path=p)),
    ]

    for filename, build in charts:
        fig = build(ARTIFACTS_DIR / filename)
        plt.close(fig)

    print(f"\n   ✅ {len(charts)} trend charts → artifacts/\n")


if __name__ == "__main__":
    main()
