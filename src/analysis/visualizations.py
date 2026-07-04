"""
visualizations.py — Temporal Taste Visualizations
===================================================
Publication-quality visualizations for the Taste Drift analysis.

All plots follow a consistent dark theme (#0d1117 background) to match
the existing project aesthetic and create a cohesive portfolio presentation.

Visualization Index:
    1. Drift Radar:        Overlaid radar charts comparing acoustic profiles across time ranges
    2. Temporal Heatmap:   Features × time ranges, colored by normalized value
    3. UMAP by Time Range: Taste map scatter plot, colored by temporal window
    4. Genre Flow:         Horizontal bar chart showing genre distribution shift
    5. Feature Distributions: Violin/box plots per feature × time range

Design Philosophy:
    Every visualization should answer a specific question a recruiter or
    hiring manager would ask:
        - "How does Jordan's taste evolve?" → Drift Radar
        - "Which features change most?" → Temporal Heatmap
        - "Do listening clusters shift?" → UMAP by Time Range
        - "Are genres changing?" → Genre Flow
"""

from pathlib import Path
from typing import Optional, Union

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .drift import (
    DRIFT_FEATURE_COLS,
    FEATURE_LABELS,
)

# ── Color Palette ──
# Consistent temporal colors across all visualizations
TIME_RANGE_COLORS = {
    "short_term": "#7ee787",   # Green — recent / fresh
    "medium_term": "#58a6ff",  # Blue — balanced / moderate
    "long_term": "#f778ba",    # Pink — historical / established
}

TIME_RANGE_LABELS = {
    "short_term": "Last 4 Weeks",
    "medium_term": "Last 6 Months",
    "long_term": "All Time",
}

# ── Dark theme base ──
BG_COLOR = "#0d1117"
CARD_COLOR = "#161b22"
BORDER_COLOR = "#30363d"
TEXT_COLOR = "#f0f6fc"
TEXT_MUTED = "#8b949e"
TEXT_DIM = "#484f58"


def plot_drift_radar(
    centroids: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
    corpus_stats: Optional[tuple[pd.Series, pd.Series]] = None,
    title: str = "Acoustic Profile — Taste Drift Radar",
    figsize: tuple = (10, 10),
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Overlaid radar/spider chart comparing acoustic profiles across time ranges.

    Each time range is a polygon on the radar. Where polygons diverge,
    taste is shifting. Where they overlap, taste is stable.

    Normalization (this is what makes the chart honest or dishonest):
        - With ``corpus_stats`` (per-feature mean, std over TRACKS): axes are
          σ-shifts vs the corpus mean — 0.5 radius = corpus mean, each ring
          0.25 = 1σ, full scale ±2σ. Visual divergence now MEANS effect size,
          matching the drift score's units (journal #10).
        - Without (legacy fallback): min-max across the centroid rows. With
          only 3 windows this pins every axis to 0 and 1 by construction and
          amplifies sub-1% differences to full scale — avoid for real data.

    Args:
        centroids:     DataFrame from compute_temporal_centroids().
        feature_cols:  Features to include on the radar. Max ~10 for readability.
        corpus_stats:  Optional (mean, std) Series per feature, computed over
                       the track-level fact table.
        title:         Chart title.
        figsize:       Figure dimensions.
        save_path:     Optional path to save.

    Returns:
        matplotlib Figure.
    """
    if feature_cols is None:
        feature_cols = DRIFT_FEATURE_COLS

    available = [c for c in feature_cols if c in centroids.columns]
    if len(available) < 3:
        print("   ⚠️  Need at least 3 features for radar chart")
        return plt.figure()

    values_by_tr = {}
    if corpus_stats is not None:
        # ── σ-shift normalization: radius 0.5 = corpus mean, ring = 1σ ──
        mean, std = corpus_stats
        mean = mean[available].values.astype(np.float64)
        std = std[available].values.astype(np.float64)
        std[std < 1e-8] = 1.0
        for _, row in centroids.iterrows():
            z = (row[available].values.astype(np.float64) - mean) / std
            values_by_tr[row["time_range"]] = np.clip(0.5 + z / 4.0, 0.0, 1.0)
    else:
        # ── Legacy min-max across windows (artifact-prone at n=3) ──
        all_values = centroids[available].values
        col_min = all_values.min(axis=0)
        col_range = all_values.max(axis=0) - col_min
        col_range[col_range < 1e-8] = 1.0  # prevent div by zero
        for _, row in centroids.iterrows():
            raw = row[available].values.astype(np.float64)
            values_by_tr[row["time_range"]] = (raw - col_min) / col_range

    # ── Build radar ──
    n = len(available)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]  # close the polygon

    fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    for tr in ["long_term", "medium_term", "short_term"]:  # plot back-to-front
        if tr not in values_by_tr:
            continue
        vals = values_by_tr[tr].tolist()
        vals += vals[:1]
        color = TIME_RANGE_COLORS.get(tr, "#ffffff")
        label = TIME_RANGE_LABELS.get(tr, tr)

        ax.plot(angles, vals, "o-", linewidth=2.5, color=color, markersize=6, label=label, zorder=3)
        ax.fill(angles, vals, alpha=0.08, color=color)

    # ── Labels ──
    labels = [FEATURE_LABELS.get(c, c) for c in available]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, color=TEXT_COLOR, fontsize=10, fontweight="500")

    if corpus_stats is not None:
        ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["−2σ", "−1σ", "mean", "+1σ", "+2σ"],
                           color=TEXT_DIM, fontsize=8)
    else:
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], color=TEXT_DIM, fontsize=8)
    ax.set_ylim(0, 1.1)

    # ── Styling ──
    ax.spines["polar"].set_color(BORDER_COLOR)
    ax.grid(color=BORDER_COLOR, alpha=0.4, linewidth=0.5)
    ax.set_title(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", pad=25, y=1.08)

    legend = ax.legend(
        loc="lower right", bbox_to_anchor=(1.3, -0.05),
        facecolor=CARD_COLOR, edgecolor=BORDER_COLOR,
        labelcolor=TEXT_COLOR, fontsize=11, title="Time Range",
        title_fontsize=12,
    )
    legend.get_title().set_color(TEXT_COLOR)

    plt.tight_layout()

    if save_path:
        _save_figure(fig, save_path, "drift radar")

    return fig


def plot_temporal_heatmap(
    centroids: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
    corpus_stats: Optional[tuple[pd.Series, pd.Series]] = None,
    title: str = "Feature Intensity — Temporal Heatmap",
    figsize: tuple = (14, 6),
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Heatmap: features (x-axis) × time ranges (y-axis).

    With ``corpus_stats`` (per-feature mean/std over tracks), cells are the
    centroid's σ-shift vs the corpus mean on a diverging colormap (±1σ full
    scale) — color intensity means effect size, matching the drift score.
    Without, falls back to per-column min-max (artifact-prone with only 3
    windows: every column then spans the full colormap by construction).

    Cell annotations always show the RAW feature values.

    Args:
        centroids:    DataFrame from compute_temporal_centroids().
        feature_cols: Features to include. Uses DRIFT_FEATURE_COLS if None.
        corpus_stats: Optional (mean, std) Series per feature over the fact table.
        title:        Chart title.
        figsize:      Figure dimensions.
        save_path:    Optional save path.

    Returns:
        matplotlib Figure.
    """
    if feature_cols is None:
        feature_cols = DRIFT_FEATURE_COLS

    available = [c for c in feature_cols if c in centroids.columns]

    # Sort by temporal order
    time_order = {"short_term": 0, "medium_term": 1, "long_term": 2}
    centroids_sorted = centroids.copy()
    centroids_sorted["_sort"] = centroids_sorted["time_range"].map(time_order)
    centroids_sorted = centroids_sorted.sort_values("_sort").drop(columns=["_sort"])

    matrix = centroids_sorted[available].values.astype(np.float64)

    if corpus_stats is not None:
        # ── σ-shift vs corpus mean, diverging scale (±1σ) ──
        mean, std = corpus_stats
        mean_v = mean[available].values.astype(np.float64)
        std_v = std[available].values.astype(np.float64)
        std_v[std_v < 1e-8] = 1.0
        normalized = (matrix - mean_v) / std_v
        cmap, vmin, vmax = "coolwarm", -1.0, 1.0
        cbar_label = "Centroid shift vs corpus mean (σ)"
        # annotation contrast: extremes of coolwarm are dark
        def _text_color(norm_val: float) -> str:
            return "black" if abs(norm_val) < 0.5 else "white"
    else:
        # ── Legacy per-column min-max ──
        col_min = matrix.min(axis=0)
        col_range = matrix.max(axis=0) - col_min
        col_range[col_range < 1e-8] = 1.0
        normalized = (matrix - col_min) / col_range
        cmap, vmin, vmax = "magma", 0.0, 1.0
        cbar_label = "Normalized Intensity"
        def _text_color(norm_val: float) -> str:
            return "white" if norm_val < 0.5 else "black"

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    im = ax.imshow(normalized, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)

    # ── Labels ──
    x_labels = [FEATURE_LABELS.get(c, c) for c in available]
    y_labels = [TIME_RANGE_LABELS.get(tr, tr) for tr in centroids_sorted["time_range"]]

    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, rotation=45, ha="right", color=TEXT_COLOR, fontsize=9)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, color=TEXT_COLOR, fontsize=11)

    # ── Annotate cells with values ──
    for i in range(normalized.shape[0]):
        for j in range(normalized.shape[1]):
            val = matrix[i, j]
            # Format based on magnitude
            if abs(val) >= 100:
                text = f"{val:.0f}"
            elif abs(val) >= 1:
                text = f"{val:.2f}"
            else:
                text = f"{val:.3f}"
            ax.text(j, i, text, ha="center", va="center", fontsize=7,
                    color=_text_color(float(normalized[i, j])), fontweight="500")

    # ── Colorbar ──
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label(cbar_label, color=TEXT_MUTED, fontsize=10)
    cbar.ax.tick_params(colors=TEXT_MUTED, labelsize=8)

    ax.set_title(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", pad=15)

    for spine in ax.spines.values():
        spine.set_color(BORDER_COLOR)

    plt.tight_layout()

    if save_path:
        _save_figure(fig, save_path, "temporal heatmap")

    return fig


def plot_umap_by_time_range(
    fact_df: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
    title: str = "Musical Taste Map — Colored by Time Range",
    figsize: tuple = (14, 10),
    annotate: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    UMAP scatter plot of all tracks, colored by time range.

    This is the most impactful visualization for the portfolio:
    it shows whether short-term tracks cluster differently from
    long-term tracks — visual proof of taste drift.

    Args:
        fact_df:      fact_listening_features DataFrame.
        feature_cols: Feature columns for UMAP input.
        title:        Chart title.
        figsize:      Figure dimensions.
        annotate:     If True, label points with track names.
        save_path:    Optional save path.

    Returns:
        matplotlib Figure.
    """
    try:
        import umap
    except ImportError:
        print("   ⚠️  umap-learn required. Install: pip install umap-learn")
        return plt.figure()

    if feature_cols is None:
        feature_cols = DRIFT_FEATURE_COLS

    available = [c for c in feature_cols if c in fact_df.columns]
    if len(available) < 3:
        print(f"   ⚠️  Need at least 3 feature columns, found {len(available)}")
        return plt.figure()

    # ── Prepare vectors ──
    vectors = fact_df[available].fillna(0).values.astype(np.float32)
    time_ranges = fact_df["time_range"].values if "time_range" in fact_df.columns else ["unknown"] * len(fact_df)
    track_names = fact_df["track_name"].values if "track_name" in fact_df.columns else [f"Track {i}" for i in range(len(fact_df))]

    if len(vectors) < 4:
        print(f"   ⚠️  UMAP requires at least 4 samples, got {len(vectors)}")
        return plt.figure()

    # ── UMAP projection ──
    n_neighbors = min(15, len(vectors) - 1)
    reducer = umap.UMAP(
        n_neighbors=n_neighbors, min_dist=0.15,
        n_components=2, metric="cosine", random_state=42,
    )
    coords = reducer.fit_transform(vectors)

    # ── Plot ──
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(CARD_COLOR)

    for tr in ["long_term", "medium_term", "short_term"]:
        mask = np.array([t == tr for t in time_ranges])
        if not mask.any():
            continue
        color = TIME_RANGE_COLORS.get(tr, "#ffffff")
        label = TIME_RANGE_LABELS.get(tr, tr)
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            c=color, label=label, s=100, alpha=0.85,
            edgecolors="white", linewidths=0.5, zorder=3,
        )

    # ── Annotations ──
    if annotate and len(track_names) <= 50:
        for i, name in enumerate(track_names):
            display = str(name)[:22] + "…" if len(str(name)) > 22 else str(name)
            ax.annotate(
                display, (coords[i, 0], coords[i, 1]),
                fontsize=6, color=TEXT_MUTED, alpha=0.8,
                xytext=(5, 5), textcoords="offset points",
                path_effects=[pe.withStroke(linewidth=2, foreground=CARD_COLOR)],
            )

    # ── Styling ──
    ax.set_xlabel("UMAP 1", color=TEXT_MUTED, fontsize=11)
    ax.set_ylabel("UMAP 2", color=TEXT_MUTED, fontsize=11)
    ax.set_title(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", pad=15)
    ax.tick_params(colors=TEXT_DIM, labelsize=9)
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    for spine in ax.spines.values():
        spine.set_color(BORDER_COLOR)

    legend = ax.legend(
        loc="upper right", facecolor=CARD_COLOR, edgecolor=BORDER_COLOR,
        labelcolor=TEXT_COLOR, fontsize=11, title="Time Range", title_fontsize=12,
    )
    legend.get_title().set_color(TEXT_COLOR)

    ax.grid(True, alpha=0.06, color=TEXT_DIM)
    plt.tight_layout()

    if save_path:
        _save_figure(fig, save_path, "UMAP taste map")

    return fig


def plot_genre_flow(
    fact_df: pd.DataFrame,
    artist_col: str = "primary_artist_name",
    title: str = "Artist Distribution — Temporal Flow",
    figsize: tuple = (16, 8),
    top_n: int = 12,
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Grouped horizontal bar chart showing top artists per time range.

    Since genre data isn't always available from the API, we use
    artist frequency as a proxy for genre distribution.

    Args:
        fact_df:     fact_listening_features DataFrame.
        artist_col:  Column to group by (artist or genre).
        title:       Chart title.
        figsize:     Figure dimensions.
        top_n:       Number of top artists to show per time range.
        save_path:   Optional save path.

    Returns:
        matplotlib Figure.
    """
    if artist_col not in fact_df.columns or "time_range" not in fact_df.columns:
        print(f"   ⚠️  Need '{artist_col}' and 'time_range' columns")
        return plt.figure()

    time_ranges = ["short_term", "medium_term", "long_term"]

    fig, axes = plt.subplots(1, 3, figsize=figsize, sharey=False)
    fig.patch.set_facecolor(BG_COLOR)
    fig.suptitle(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", y=1.02)

    for ax, tr in zip(axes, time_ranges, strict=True):
        ax.set_facecolor(CARD_COLOR)
        subset = fact_df[fact_df["time_range"] == tr]

        if subset.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", color=TEXT_MUTED, fontsize=12)
            ax.set_title(TIME_RANGE_LABELS.get(tr, tr), color=TEXT_COLOR, fontsize=12, fontweight="bold")
            continue

        counts = subset[artist_col].value_counts().head(top_n)
        color = TIME_RANGE_COLORS.get(tr, "#58a6ff")

        y_pos = range(len(counts))
        ax.barh(y_pos, counts.values, color=color, alpha=0.85, edgecolor=BORDER_COLOR, height=0.7)
        ax.set_yticks(y_pos)
        ax.set_yticklabels([str(n)[:25] for n in counts.index], color=TEXT_COLOR, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Track Count", color=TEXT_MUTED, fontsize=9)
        ax.set_title(TIME_RANGE_LABELS.get(tr, tr), color=TEXT_COLOR, fontsize=12, fontweight="bold")
        ax.tick_params(colors=TEXT_DIM, labelsize=8)

        for spine in ax.spines.values():
            spine.set_color(BORDER_COLOR)

    plt.tight_layout()

    if save_path:
        _save_figure(fig, save_path, "genre flow")

    return fig


def plot_feature_distributions(
    fact_df: pd.DataFrame,
    feature_cols: Optional[list[str]] = None,
    title: str = "Feature Distributions by Time Range",
    figsize: Optional[tuple] = None,
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Box plots for each feature, grouped by time range.

    Shows not just the centroid (mean) but the full distribution —
    useful for identifying whether taste drift is driven by a few
    outlier tracks or a genuine shift in the entire distribution.

    Args:
        fact_df:      fact_listening_features DataFrame.
        feature_cols: Features to plot. Max ~8 for readability.
        title:        Chart title.
        figsize:      Figure dimensions (auto-calculated if None).
        save_path:    Optional save path.

    Returns:
        matplotlib Figure.
    """
    if feature_cols is None:
        # Pick the most interpretable features
        feature_cols = [
            "tempo_bpm", "rms_mean", "zcr_mean",
            "spectral_centroid_mean", "harmonic_ratio", "onset_strength_mean",
        ]

    available = [c for c in feature_cols if c in fact_df.columns]
    n_features = len(available)

    if n_features == 0:
        print("   ⚠️  No feature columns found for distribution plot")
        return plt.figure()

    n_cols = min(3, n_features)
    n_rows = (n_features + n_cols - 1) // n_cols
    if figsize is None:
        figsize = (6 * n_cols, 4 * n_rows)

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    fig.patch.set_facecolor(BG_COLOR)

    if n_features == 1:
        axes = np.array([axes])
    axes_flat = axes.flatten() if hasattr(axes, "flatten") else [axes]

    time_ranges = ["short_term", "medium_term", "long_term"]

    for idx, col in enumerate(available):
        ax = axes_flat[idx]
        ax.set_facecolor(CARD_COLOR)

        data_by_tr = []
        labels = []
        colors = []
        for tr in time_ranges:
            subset = fact_df[fact_df["time_range"] == tr][col].dropna()
            if not subset.empty:
                data_by_tr.append(subset.values)
                labels.append(TIME_RANGE_LABELS.get(tr, tr))
                colors.append(TIME_RANGE_COLORS.get(tr, "#ffffff"))

        if data_by_tr:
            # Set tick labels after the fact rather than via a boxplot kwarg —
            # matplotlib renamed boxplot(labels=) → tick_labels= in 3.9, so the
            # kwarg form breaks on newer matplotlib (caught by CI). This is
            # version-agnostic.
            bp = ax.boxplot(
                data_by_tr, patch_artist=True,
                widths=0.6, showfliers=True, flierprops={"marker": ".", "markersize": 4},
            )
            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels)
            for patch, color in zip(bp["boxes"], colors, strict=True):
                patch.set_facecolor(color)
                patch.set_alpha(0.6)
                patch.set_edgecolor("white")
            for element in ["whiskers", "caps", "medians"]:
                for line in bp[element]:
                    line.set_color(TEXT_MUTED)

        ax.set_title(FEATURE_LABELS.get(col, col), color=TEXT_COLOR, fontsize=11, fontweight="bold")
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.tick_params(axis="x", colors=TEXT_COLOR, labelsize=9)

        for spine in ax.spines.values():
            spine.set_color(BORDER_COLOR)

    # Hide unused axes
    for idx in range(n_features, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", y=1.02)
    plt.tight_layout()

    if save_path:
        _save_figure(fig, save_path, "feature distributions")

    return fig


def _save_figure(fig: plt.Figure, save_path: Union[str, Path], name: str) -> None:
    """Save a figure to disk with consistent settings."""
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight")
    print(f"   🖼️  Saved {name} → {save_path.name}")
