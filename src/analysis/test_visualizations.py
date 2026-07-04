"""
test_visualizations.py — Trend-chart tests (synthetic data only)
=================================================================
SPEC P3 acceptance support: each chart function renders from a fact-shaped
DataFrame alone and writes a non-trivial PNG. Headless (Agg), no warehouse.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from src.analysis.drift import DRIFT_FEATURE_COLS, compute_temporal_centroids
from src.analysis.visualizations import (
    plot_drift_radar,
    plot_feature_distributions,
    plot_genre_flow,
    plot_temporal_heatmap,
)


@pytest.fixture()
def fact() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for tr, level in [("short_term", 2.0), ("medium_term", 1.0), ("long_term", 0.5)]:
        for i in range(6):
            rows.append({
                "spotify_track_id": f"{tr}_{i}", "track_name": f"{tr} track {i}",
                "primary_artist_name": f"Artist {i % 3}", "time_range": tr,
                "rank": i + 1,
                **{c: float(rng.normal(level, 0.1)) for c in DRIFT_FEATURE_COLS},
            })
    return pd.DataFrame(rows)


def _assert_png(path):
    assert path.exists()
    assert path.stat().st_size > 5_000  # a real rendered chart, not a stub


class TestCharts:
    def test_drift_radar_writes_png(self, fact, tmp_path):
        out = tmp_path / "radar.png"
        fig = plot_drift_radar(compute_temporal_centroids(fact), save_path=out)
        plt.close(fig)
        _assert_png(out)

    def test_temporal_heatmap_writes_png(self, fact, tmp_path):
        out = tmp_path / "heatmap.png"
        fig = plot_temporal_heatmap(compute_temporal_centroids(fact), save_path=out)
        plt.close(fig)
        _assert_png(out)

    def test_feature_distributions_writes_png(self, fact, tmp_path):
        out = tmp_path / "dist.png"
        fig = plot_feature_distributions(fact, save_path=out)
        plt.close(fig)
        _assert_png(out)

    def test_genre_flow_writes_png(self, fact, tmp_path):
        out = tmp_path / "flow.png"
        fig = plot_genre_flow(fact, save_path=out)
        plt.close(fig)
        _assert_png(out)


class TestSigmaNormalization:
    def test_radar_sigma_mode_writes_png(self, fact, tmp_path):
        out = tmp_path / "radar_sigma.png"
        stats = (fact[DRIFT_FEATURE_COLS].mean(), fact[DRIFT_FEATURE_COLS].std())
        fig = plot_drift_radar(compute_temporal_centroids(fact),
                               corpus_stats=stats, save_path=out)
        plt.close(fig)
        _assert_png(out)

    def test_heatmap_sigma_mode_writes_png(self, fact, tmp_path):
        out = tmp_path / "heatmap_sigma.png"
        stats = (fact[DRIFT_FEATURE_COLS].mean(), fact[DRIFT_FEATURE_COLS].std())
        fig = plot_temporal_heatmap(compute_temporal_centroids(fact),
                                    corpus_stats=stats, save_path=out)
        plt.close(fig)
        _assert_png(out)

    def test_sigma_mode_handles_zero_std(self, fact, tmp_path):
        # A constant feature must not divide by zero
        fact = fact.copy()
        fact["tempo_bpm"] = 120.0
        stats = (fact[DRIFT_FEATURE_COLS].mean(), fact[DRIFT_FEATURE_COLS].std())
        fig = plot_drift_radar(compute_temporal_centroids(fact),
                               corpus_stats=stats)
        plt.close(fig)  # must not raise


class TestDegenerateInputs:
    def test_radar_needs_three_features(self, fact, tmp_path):
        centroids = compute_temporal_centroids(fact)[["time_range", "tempo_bpm", "rms_mean"]]
        fig = plot_drift_radar(centroids, feature_cols=["tempo_bpm", "rms_mean"])
        plt.close(fig)  # warns and returns an empty figure — must not raise

    def test_distributions_without_features_returns_empty(self, tmp_path):
        bare = pd.DataFrame({"time_range": ["short_term"], "track_name": ["x"]})
        fig = plot_feature_distributions(bare)
        plt.close(fig)  # must not raise

    def test_genre_flow_missing_columns_returns_empty(self):
        fig = plot_genre_flow(pd.DataFrame({"a": [1]}))
        plt.close(fig)  # must not raise


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
