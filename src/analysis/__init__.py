"""
analysis — Temporal Taste Analysis & Visualization
====================================================
Computes taste drift metrics and generates publication-quality
visualizations of how musical preferences evolve over time.

Usage:
    from src.analysis import (
        compute_taste_drift,
        compute_temporal_centroids,
        plot_drift_radar,
        plot_temporal_heatmap,
        plot_umap_by_time_range,
    )
"""

from .drift import compute_feature_deltas, compute_taste_drift, compute_temporal_centroids
from .visualizations import (
    plot_drift_radar,
    plot_feature_distributions,
    plot_genre_flow,
    plot_temporal_heatmap,
    plot_umap_by_time_range,
)

__all__ = [
    "compute_feature_deltas", "compute_taste_drift", "compute_temporal_centroids",
    "plot_drift_radar", "plot_feature_distributions", "plot_genre_flow",
    "plot_temporal_heatmap", "plot_umap_by_time_range",
]
