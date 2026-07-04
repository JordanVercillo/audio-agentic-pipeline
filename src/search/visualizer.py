"""
visualizer.py — UMAP Dimensionality Reduction & Taste Visualization
=====================================================================
Projects high-dimensional audio embeddings into 2D/3D space for
visual exploration of musical taste clusters.

Why UMAP over PCA or t-SNE? (per 03_data_orchestrator.md):
    - PCA: Only captures linear variance. Music similarity is
      highly nonlinear (a jazz track and a funk track can share
      rhythmic features but diverge spectrally). PCA misses this.
    - t-SNE: Good local structure, but DESTROYS global relationships.
      All clusters appear equally spaced regardless of actual similarity.
      You can't trust the distance between clusters.
    - UMAP: Preserves BOTH local neighborhoods (similar tracks cluster
      tightly) AND global topology (jazz cluster is closer to funk
      than to death metal). This is critical for taste analysis.

UMAP Parameters (intuition):
    - n_neighbors: How many nearby points define "local." Higher values
      sacrifice fine-grained clusters for smoother global structure.
      Default 15 is a good balance for music collections.
    - min_dist: How tightly packed the 2D projection is. Lower values
      (0.0-0.1) create dense, separated clusters. Higher values (0.5+)
      spread points out more uniformly. We use 0.1 for clear genre clumps.
    - metric: "cosine" — matches our FAISS search metric for consistency.

Reference: 03_data_orchestrator.md — "Dimensionality Reduction (EDA)"
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np

try:
    import umap
except ImportError:
    raise ImportError(
        "umap-learn is required for visualization.\n"
        "Install: pip install umap-learn"
    ) from None

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

from .config import VectorStoreConfig

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UMAP PROJECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_umap(
    vectors: np.ndarray,
    config: Optional[VectorStoreConfig] = None,
) -> np.ndarray:
    """
    Project high-dimensional vectors into 2D/3D space via UMAP.

    Args:
        vectors: Shape (n_samples, embedding_dim), float32.
        config:  Optional VectorStoreConfig with UMAP parameters.

    Returns:
        Projected coordinates, shape (n_samples, n_components).
        n_components is typically 2 (for scatter plots) or 3 (for 3D).
    """
    config = config or VectorStoreConfig()

    # UMAP requires at least n_neighbors + 1 samples
    n_samples = vectors.shape[0]
    n_neighbors = min(config.umap_n_neighbors, n_samples - 1)

    if n_samples < 4:
        raise ValueError(
            f"UMAP requires at least 4 samples, got {n_samples}. "
            f"Add more tracks to the collection."
        )

    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=config.umap_min_dist,
        n_components=config.umap_n_components,
        metric="cosine",  # Match FAISS metric for consistency
        random_state=config.umap_random_state,
    )

    projection = reducer.fit_transform(vectors)
    return projection.astype(np.float32)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASTE MAP VISUALIZATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def plot_taste_map(
    projection: np.ndarray,
    labels: Optional[list[str]] = None,
    colors: Optional[Union[list[str], np.ndarray]] = None,
    color_label: str = "Genre",
    title: str = "Musical Taste Map (UMAP)",
    figsize: tuple = (14, 10),
    point_size: int = 80,
    sizes: Optional[np.ndarray] = None,
    category_colors: Optional[dict[str, str]] = None,
    annotate: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Create a publication-quality 2D scatter plot of the UMAP projection.

    Designed for visualizing clusters of musical genres, artists, or
    acoustic similarity in the user's listening history.

    Args:
        projection:  Shape (n, 2) UMAP coordinates.
        labels:      Text labels per point (e.g., track names). Shown on hover/annotation.
        colors:      Color per point. Can be:
                     - List of category strings (auto-mapped to colormap)
                     - List of hex colors
                     - Numpy array of floats (mapped to colormap)
        color_label: Legend title for the color dimension.
        title:       Plot title.
        figsize:     Figure dimensions.
        point_size:  Marker size (uniform; ignored where ``sizes`` is given).
        sizes:       Optional per-point sizes, shape (n,) — e.g. encode how
                     many time ranges a track appears in.
        category_colors: Optional {category: hex} overriding the colormap for
                     specific categories (e.g. force "Unknown" to grey).
        annotate:    If True, add text labels near each point.
        save_path:   If provided, save the figure to this path.

    Returns:
        matplotlib Figure object.
    """
    fig, ax = plt.subplots(figsize=figsize)

    # ── Dark theme (matching existing project aesthetic) ──
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    # ── Process colors ──
    if colors is not None:
        unique_cats = sorted(set(colors))
        # Use a perceptually uniform colormap with enough distinction
        cmap = plt.get_cmap("tab20", len(unique_cats))  # plt.cm.get_cmap removed in mpl 3.9
        cat_to_idx = {cat: i for i, cat in enumerate(unique_cats)}
        overrides = category_colors or {}

        for cat in unique_cats:
            mask = np.array([c == cat for c in colors])
            cat_color = overrides.get(str(cat), cmap(cat_to_idx[cat]))
            ax.scatter(
                projection[mask, 0],
                projection[mask, 1],
                c=[cat_color],
                label=str(cat),
                s=sizes[mask] if sizes is not None else point_size,
                alpha=0.8,
                edgecolors="#30363d",
                linewidth=0.5,
            )

        legend = ax.legend(
            title=color_label,
            loc="upper right",
            facecolor="#161b22",
            edgecolor="#30363d",
            labelcolor="#c9d1d9",
            title_fontsize=11,
            fontsize=9,
        )
        legend.get_title().set_color("#f0f6fc")
    else:
        ax.scatter(
            projection[:, 0],
            projection[:, 1],
            c="#58a6ff",
            s=sizes if sizes is not None else point_size,
            alpha=0.8,
            edgecolors="#1f6feb",
            linewidth=0.5,
        )

    # ── Annotations ──
    if annotate and labels is not None:
        for i, label in enumerate(labels):
            # Truncate long labels
            display_label = label[:25] + "…" if len(label) > 25 else label
            ax.annotate(
                display_label,
                (projection[i, 0], projection[i, 1]),
                fontsize=7,
                color="#8b949e",
                alpha=0.9,
                xytext=(5, 5),
                textcoords="offset points",
                path_effects=[
                    pe.withStroke(linewidth=2, foreground="#0d1117")
                ],
            )

    # ── Styling ──
    ax.set_title(title, color="#f0f6fc", fontsize=16, fontweight="bold", pad=15)
    ax.set_xlabel("UMAP 1", color="#8b949e", fontsize=11)
    ax.set_ylabel("UMAP 2", color="#8b949e", fontsize=11)
    ax.tick_params(colors="#484f58", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")

    # Remove axis tick values (UMAP dimensions are not interpretable)
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    plt.tight_layout()

    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, facecolor="#0d1117", bbox_inches="tight")
        print(f"   🖼️  Saved taste map → {save_path.name}")

    return fig


def plot_similarity_radar(
    features_dict: dict[str, float],
    title: str = "Track Acoustic Profile",
    figsize: tuple = (8, 8),
    save_path: Optional[Union[str, Path]] = None,
) -> plt.Figure:
    """
    Create a radar/spider chart showing a track's acoustic feature profile.

    Useful for comparing individual tracks across dimensions like
    energy, tempo, harmonic ratio, spectral brightness, etc.

    Args:
        features_dict: {feature_name: normalized_value_0_to_1}
        title:         Chart title.
        figsize:       Figure size.
        save_path:     Optional save path.

    Returns:
        matplotlib Figure.
    """
    categories = list(features_dict.keys())
    values = list(features_dict.values())
    n = len(categories)

    # Close the polygon
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    values += values[:1]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    # Plot
    ax.plot(angles, values, "o-", linewidth=2, color="#58a6ff", markersize=6)
    ax.fill(angles, values, alpha=0.15, color="#58a6ff")

    # Labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color="#c9d1d9", fontsize=10)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], color="#484f58", fontsize=8)
    ax.set_ylim(0, 1.05)

    # Grid styling
    ax.spines["polar"].set_color("#30363d")
    ax.grid(color="#30363d", alpha=0.5)
    ax.set_title(title, color="#f0f6fc", fontsize=14, fontweight="bold", pad=20)

    plt.tight_layout()

    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, facecolor="#0d1117", bbox_inches="tight")
        print(f"   🖼️  Saved radar → {save_path.name}")

    return fig
