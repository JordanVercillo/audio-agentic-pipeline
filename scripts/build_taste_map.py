"""
build_taste_map.py — SPEC P1: the taste map (one command → the money visual)
=============================================================================
Warehouse → 77-dim clustering → UMAP → genre-colored taste map.

    python scripts/build_taste_map.py

Outputs:
    data/warehouse/modeled/cluster_assignments.parquet  (bridge-keyed, rebuildable)
    artifacts/taste_map.png                             (committable README hero)

Deterministic: fixed seeds in clustering (random_state=42) and UMAP
(VectorStoreConfig.umap_random_state=42) — same warehouse in, same map out.
"""

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — we only save files
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s — %(message)s")

# Fixed palette: dark-theme-vivid, collision-checked for the big buckets
# (Indie blue vs Blues cyan vs Electronic ice; Rock orange vs Hip-Hop gold);
# Unknown deliberately recedes into the background.
GENRE_PALETTE = {
    "Indie & Alt": "#58a6ff",
    "Punk & Emo":  "#f85149",
    "Rock":        "#f0883e",
    "Folk":        "#3fb950",
    "Metal":       "#a371f7",
    "Blues":       "#39c5cf",
    "Pop":         "#f778ba",
    "Classical":   "#e3b341",
    "Jazz":        "#eac54f",
    "Hip-Hop":     "#d4a72c",
    "Electronic":  "#a5d6ff",
    "R&B & Funk":  "#d2a8ff",
    "Country":     "#7ee787",
    "Latin":       "#ffb3d8",
    "Other":       "#8b949e",
    "Unknown":     "#484f58",
}

# Marker area by temporal persistence (1/2/3 time ranges).
SIZE_BY_RANGES = {1: 45, 2: 100, 3: 185}


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    from src.analysis.clustering import build_cluster_assignments
    from src.search.visualizer import plot_taste_map

    print("=" * 60)
    print("  🗺️  Taste Map builder (SPEC P1)")
    print("=" * 60)

    assignments, summary = build_cluster_assignments()

    projection = assignments[["umap_x", "umap_y"]].to_numpy()
    buckets = assignments["genre_bucket"].tolist()
    sizes = assignments["n_time_ranges"].map(SIZE_BY_RANGES).to_numpy(dtype=float)

    n = len(assignments)
    covered = int((assignments["genre_bucket"] != "Unknown").sum())

    fig = plot_taste_map(
        projection,
        colors=buckets,
        category_colors=GENRE_PALETTE,
        sizes=sizes,
        color_label="Genre",
        title=f"Taste Map — {n} tracks in 77-dim acoustic space (UMAP + KMeans)",
        annotate=False,
    )
    ax = fig.axes[0]

    # ── Cluster labels at cluster medians: acoustic character (from the DSP
    #    features) + dominant genre — differentiates clusters even when one
    #    artist/genre dominates the whole corpus. ──
    import matplotlib.patheffects as pe
    for _, row in summary.iterrows():
        mask = assignments["cluster_id"] == row["cluster_id"]
        cx = float(np.median(projection[mask.to_numpy(), 0]))
        cy = float(np.median(projection[mask.to_numpy(), 1]))
        ax.annotate(
            f"{row['acoustic_label']}\nmostly {row['dominant_genre']}",
            (cx, cy),
            fontsize=11, fontweight="bold", color="#f0f6fc",
            ha="center", va="center",
            path_effects=[pe.withStroke(linewidth=3.5, foreground="#0d1117")],
        )

    # ── Size legend (temporal persistence) ──
    size_handles = [
        plt.scatter([], [], s=s, c="#8b949e", edgecolors="#30363d", linewidth=0.5,
                    label={1: "1 time range", 2: "2 time ranges",
                           3: "all 3 (persistent favorite)"}[k])
        for k, s in SIZE_BY_RANGES.items()
    ]
    size_legend = ax.legend(
        handles=size_handles, title="Appears in", loc="lower left",
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9",
        title_fontsize=10, fontsize=9,
    )
    size_legend.get_title().set_color("#f0f6fc")
    # Re-add the genre legend (a second ax.legend() call replaces the first)
    handles, labels_ = ax.get_legend_handles_labels()
    genre_only = [(h, lab) for h, lab in zip(handles, labels_, strict=True) if lab in GENRE_PALETTE]
    genre_legend = ax.legend(
        [h for h, _ in genre_only], [lab for _, lab in genre_only],
        title="Genre", loc="upper right",
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9",
        title_fontsize=11, fontsize=9,
    )
    genre_legend.get_title().set_color("#f0f6fc")
    ax.add_artist(size_legend)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "taste_map.png"
    fig.savefig(out_path, dpi=200, facecolor="#0d1117", bbox_inches="tight")
    plt.close(fig)

    print(f"\n   🖼️  Saved → {out_path.relative_to(PROJECT_ROOT)}")
    print(f"   📊 Genre coverage: {covered}/{n} tracks "
          f"({n - covered} Unknown — sparse 2026 API genre data)")
    print("   ✅ Taste map complete\n")


if __name__ == "__main__":
    main()
