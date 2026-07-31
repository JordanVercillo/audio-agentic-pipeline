"""
clustering.py — Genre Clustering for the Taste Map (SPEC P1)
=============================================================
Clusters the listening corpus by acoustic similarity and attaches the
coarse-genre + temporal metadata the taste map visual needs.

Design decisions:
    - CLUSTER IN THE 77-DIM CONTRACT SPACE. The feature subset used here is
      exactly the membership of ``TrackFeatures.to_summary_vector()`` — the
      frozen similarity contract used by FAISS. Clustering and similarity
      search therefore agree about what "close" means.
    - COSINE GEOMETRY. Features are standardized (zero mean / unit variance
      per column, so tempo's 60–200 BPM range can't drown out RMS's 0–1),
      then L2-normalized per row: KMeans' euclidean distance on unit vectors
      is monotonic with cosine distance (ADR-003 doctrine).
    - DETERMINISTIC. Fixed random_state everywhere; k chosen by silhouette
      over a small range — same corpus in, same clusters out.
    - COARSE GENRES BY ORDERED RULES. Spotify's 2026 genre tags are sparse
      micro-genres ("egg punk", "madchester"). An ordered keyword table maps
      them to ~10 readable buckets; first matching rule wins, so specific
      buckets (Punk & Emo) outrank generic ones (Rock) — "pop punk" is punk,
      not pop.

Outputs:
    ``data/warehouse/modeled/cluster_assignments.parquet`` — one row per
    track, keyed on the bridge key (audit-clean by construction).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Above this population, score k-selection on a deterministic sample instead of
# the full O(N²) pairwise matrix (P4.6.4). Note the stored `silhouette` then
# becomes a sampled estimate — which is fine because it is REPORTED, never a
# gate (D-62: it drops as a corpus grows, so gating on it would freeze the
# model at its smallest population).
_SILHOUETTE_SAMPLE = 5000

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  THE 77-DIM CONTRACT COLUMNS (mirror of to_summary_vector)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VECTOR_77_COLUMNS: list[str] = (
    # Rhythm (4)
    ["tempo_bpm", "onset_strength_mean", "onset_strength_std", "beats_per_sec"]
    # Energy (4)
    + ["rms_mean", "rms_std", "zcr_mean", "zcr_std"]
    # Timbre — MFCCs (26)
    + [f"mfcc_mean_{i}" for i in range(13)]
    + [f"mfcc_std_{i}" for i in range(13)]
    # Spectral shape (4)
    + ["spectral_centroid_mean", "spectral_centroid_std",
       "spectral_rolloff_mean", "spectral_rolloff_std"]
    # Spectral contrast (14)
    + [f"spectral_contrast_mean_{i}" for i in range(7)]
    + [f"spectral_contrast_std_{i}" for i in range(7)]
    # Chroma (24)
    + [f"chroma_mean_{pc}" for pc in _PITCH_CLASSES]
    + [f"chroma_std_{pc}" for pc in _PITCH_CLASSES]
    # Acousticness proxy (1)
    + ["harmonic_ratio"]
)
assert len(VECTOR_77_COLUMNS) == 77, "the similarity contract is exactly 77 dims"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COARSE GENRE MAPPING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Ordered: first bucket whose keywords match ANY of the artist's tags wins.
# Specific families before generic ones ("pop punk" → Punk & Emo, not Pop).
COARSE_GENRE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Metal",       ("metal", "metalcore", "djent")),
    ("Punk & Emo",  ("punk", "emo", "screamo", "hardcore", "grunge")),
    ("Folk",        ("folk", "acoustic", "singer-songwriter", "americana")),
    ("Classical",   ("classical", "opera", "orchestra", "baroque")),
    ("Jazz",        ("jazz", "bossa nova", "swing")),
    ("Blues",       ("blues",)),
    ("Hip-Hop",     ("hip hop", "hip-hop", "rap", "trap", "drill")),
    ("Electronic",  ("electronic", "edm", "house", "techno", "dubstep",
                     "synthwave", "drum and bass", "dance", "electro")),
    ("R&B & Funk",  ("r&b", "rnb", "soul", "funk", "motown")),
    ("Country",     ("country", "bluegrass")),
    ("Latin",       ("latin", "reggaeton", "salsa", "bachata")),
    ("Indie & Alt", ("indie", "alternative", "britpop", "madchester",
                     "new wave", "garage", "shoegaze", "lo-fi", "post-")),
    ("Pop",         ("pop", "synthpop")),
    ("Rock",        ("rock", "rock and roll")),
]

UNKNOWN_BUCKET = "Unknown"
OTHER_BUCKET = "Other"


def map_genres_to_bucket(genres: Optional[str]) -> str:
    """
    Map a comma-separated Spotify genre string to one coarse bucket.

    The FIRST rule (in COARSE_GENRE_RULES order) whose keywords substring-match
    any tag wins — deterministic and priority-ordered.

    Args:
        genres: e.g. ``"pop punk, alternative rock"`` (may be None/empty).

    Returns:
        Bucket name; ``"Unknown"`` for empty input, ``"Other"`` when tags
        exist but no rule matches.
    """
    if not genres or not str(genres).strip():
        return UNKNOWN_BUCKET

    tags = [t.strip().lower() for t in str(genres).split(",") if t.strip()]
    if not tags:
        return UNKNOWN_BUCKET

    for bucket, keywords in COARSE_GENRE_RULES:
        for tag in tags:
            if any(kw in tag for kw in keywords):
                return bucket
    return OTHER_BUCKET


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ASSEMBLY: per-track frame from the warehouse
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_track_frame(
    cleansed_dir: Optional[Union[str, Path]] = None,
    modeled_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Assemble the clustering input: one row per track with features + context.

    Joins (all on the bridge key / primary_artist_id):
        cleansed_features (77-dim source)
        + dim_tracks      (track_name, primary artist)
        + dim_artists     (genres → coarse bucket)
        + fact            (n_time_ranges: in how many temporal windows the
                           track appears — 3 = persistent favorite)

    Returns:
        DataFrame with VECTOR_77_COLUMNS + [spotify_track_id, track_name,
        primary_artist_name, genre_bucket, n_time_ranges]. Tracks without
        extracted features are excluded (can't be placed on an acoustic map).
    """
    cleansed_dir = Path(cleansed_dir or CLEANSED_DIR)
    modeled_dir = Path(modeled_dir or MODELED_DIR)

    features = pd.read_parquet(cleansed_dir / "cleansed_features.parquet", engine="pyarrow")
    dim_tracks = pd.read_parquet(modeled_dir / "dim_tracks.parquet", engine="pyarrow")
    dim_artists = pd.read_parquet(modeled_dir / "dim_artists.parquet", engine="pyarrow")
    fact = pd.read_parquet(modeled_dir / "fact_listening_features.parquet", engine="pyarrow")

    missing = [c for c in VECTOR_77_COLUMNS if c not in features.columns]
    if missing:
        raise ValueError(
            f"cleansed_features is missing {len(missing)} contract columns "
            f"(e.g. {missing[:5]}) — rerun the pipeline extract step."
        )

    frame = features[["spotify_track_id"] + VECTOR_77_COLUMNS].copy()

    # Track context
    track_cols = ["spotify_track_id", "track_name", "primary_artist_name", "primary_artist_id"]
    frame = frame.merge(
        dim_tracks[[c for c in track_cols if c in dim_tracks.columns]],
        on="spotify_track_id", how="left",
    )

    # Genre bucket via primary artist
    if "genres" in dim_artists.columns:
        frame = frame.merge(
            dim_artists[["artist_id", "genres"]],
            left_on="primary_artist_id", right_on="artist_id", how="left",
        ).drop(columns=["artist_id"])
    else:
        frame["genres"] = ""
    frame["genre_bucket"] = frame["genres"].apply(map_genres_to_bucket)

    # Temporal persistence: number of time ranges the track appears in
    n_ranges = (
        fact.groupby("spotify_track_id")["time_range"].nunique()
        .rename("n_time_ranges").reset_index()
    )
    frame = frame.merge(n_ranges, on="spotify_track_id", how="left")
    frame["n_time_ranges"] = frame["n_time_ranges"].fillna(1).astype(int)

    logger.info(
        "Track frame: %d tracks, genre coverage %d/%d",
        len(frame), int((frame["genre_bucket"] != UNKNOWN_BUCKET).sum()), len(frame),
    )
    return frame.drop(columns=["genres", "primary_artist_id"], errors="ignore")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CLUSTERING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def prepare_matrix(frame: pd.DataFrame) -> np.ndarray:
    """
    77-dim frame → standardized, L2-normalized float32 matrix.

    Standardize so no feature's scale dominates; L2-normalize rows so
    KMeans' euclidean distance behaves like cosine distance (unit sphere).
    """
    X = frame[VECTOR_77_COLUMNS].to_numpy(dtype=np.float64)
    X = StandardScaler().fit_transform(X)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (X / norms).astype(np.float32)


def cluster_tracks(
    X: np.ndarray,
    k_range: tuple[int, int] = (3, 9),
    random_state: int = 42,
) -> tuple[np.ndarray, int, float]:
    """
    KMeans with k selected by silhouette score over ``k_range`` (inclusive).

    Args:
        X:            Prepared matrix from prepare_matrix().
        k_range:      (k_min, k_max) inclusive candidate range.
        random_state: Seed — same corpus in, same clusters out.

    Returns:
        (labels, chosen_k, silhouette) for the best k.
    """
    n = X.shape[0]
    k_min, k_max = k_range
    k_max = min(k_max, n - 1)
    if n < max(4, k_min + 1):
        raise ValueError(f"Need at least {max(4, k_min + 1)} tracks to cluster, got {n}.")

    best: tuple[float, int, np.ndarray] = (-2.0, k_min, np.zeros(n, dtype=int))
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(X)
        # P4.6.4: silhouette_score is O(N²) — it builds the full pairwise
        # distance matrix, once PER CANDIDATE k. That is the only quadratic step
        # in the platform: ~7 s at 1.9k tracks, but ~3 min at 10k and hours at
        # 100k, and it runs inside the post-drain chain. Sampling is exact-enough
        # for CHOOSING k (the ranking between candidate k's is what matters, not
        # the absolute value) and deterministic via random_state, so the same
        # corpus still picks the same k. Below the threshold nothing changes.
        score = silhouette_score(
            X, labels,
            **({"sample_size": _SILHOUETTE_SAMPLE, "random_state": random_state}
               if n > _SILHOUETTE_SAMPLE else {}))
        logger.info("k=%d silhouette=%.4f%s", k, score,
                    f" (sampled {_SILHOUETTE_SAMPLE})" if n > _SILHOUETTE_SAMPLE else "")
        if score > best[0]:
            best = (score, k, labels)

    score, k, labels = best
    logger.info("Chosen k=%d (silhouette=%.4f)", k, score)
    return labels, k, float(score)


# Interpretable dims for acoustic cluster naming: (column, high-word, low-word).
_CHARACTER_DIMS: list[tuple[str, str, str]] = [
    ("rms_mean",               "Loud",      "Quiet"),
    ("tempo_bpm",              "Fast",      "Slow"),
    ("harmonic_ratio",         "Harmonic",  "Percussive"),
    ("spectral_centroid_mean", "Bright",    "Dark"),
    ("zcr_mean",               "Noisy",     "Smooth"),
    ("onset_strength_mean",    "Punchy",    "Gentle"),
]


def _acoustic_label(cluster_frame: pd.DataFrame, corpus: pd.DataFrame, top_n: int = 2) -> str:
    """
    Name a cluster by its most distinguishing acoustic dimensions.

    Why: genre tags can't tell clusters apart when one artist/genre dominates
    the corpus (all clusters would be labeled "Indie (Muse)"). The DSP
    features CAN — each cluster gets the top-|z| interpretable dims of its
    centroid vs the corpus, e.g. "Loud · Fast" vs "Harmonic · Dark".
    """
    scored: list[tuple[float, str]] = []
    for col, hi, lo in _CHARACTER_DIMS:
        std = float(corpus[col].std())
        if std == 0 or np.isnan(std):
            continue
        z = (float(cluster_frame[col].mean()) - float(corpus[col].mean())) / std
        scored.append((abs(z), hi if z > 0 else lo))
    scored.sort(reverse=True)
    return " · ".join(word for _, word in scored[:top_n]) if scored else "Mixed"


def describe_clusters(frame: pd.DataFrame) -> pd.DataFrame:
    """
    One summary row per cluster: size, acoustic label (distinguishing DSP
    character vs the corpus), dominant genre bucket, top artist.
    Used by the taste-map annotations and (later) the insight engine.
    """
    def _top(series: pd.Series, exclude: tuple = ()) -> str:
        counts = series[~series.isin(exclude)].value_counts()
        return str(counts.index[0]) if len(counts) else UNKNOWN_BUCKET

    has_features = all(col in frame.columns for col, _, _ in _CHARACTER_DIMS)

    rows = []
    for cid, grp in frame.groupby("cluster_id"):
        rows.append({
            "cluster_id": int(cid),
            "n_tracks": len(grp),
            "acoustic_label": _acoustic_label(grp, frame) if has_features else "Mixed",
            "dominant_genre": _top(grp["genre_bucket"], exclude=(UNKNOWN_BUCKET,)),
            "top_artist": _top(grp["primary_artist_name"]),
        })
    return pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)


def build_cluster_assignments(
    cleansed_dir: Optional[Union[str, Path]] = None,
    modeled_dir: Optional[Union[str, Path]] = None,
    k_range: tuple[int, int] = (3, 9),
    random_state: int = 42,
    write: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    End-to-end: warehouse → clustered + UMAP-projected track assignments.

    Returns:
        (assignments, cluster_summary). When ``write`` is True, assignments
        land at ``modeled/cluster_assignments.parquet`` (bridge-keyed, one
        row per track — audit-clean).
    """
    from src.search.visualizer import compute_umap  # local import: optional dep chain

    modeled_dir = Path(modeled_dir or MODELED_DIR)
    frame = load_track_frame(cleansed_dir=cleansed_dir, modeled_dir=modeled_dir)

    X = prepare_matrix(frame)
    labels, k, silhouette = cluster_tracks(X, k_range=k_range, random_state=random_state)
    frame["cluster_id"] = labels

    projection = compute_umap(X)  # cosine metric, seeded via VectorStoreConfig
    frame["umap_x"] = projection[:, 0]
    frame["umap_y"] = projection[:, 1]

    assignments = frame[[
        "spotify_track_id", "cluster_id", "umap_x", "umap_y",
        "genre_bucket", "n_time_ranges", "track_name", "primary_artist_name",
    ]].copy()
    summary = describe_clusters(frame)

    print(f"   🎛️  Clustered {len(assignments)} tracks → k={k} "
          f"(silhouette={silhouette:.3f})")
    for _, row in summary.iterrows():
        print(f"      cluster {row.cluster_id}: {row.n_tracks:3d} tracks — "
              f"{row.acoustic_label} | {row.dominant_genre} "
              f"(top artist: {row.top_artist})")

    if write:
        modeled_dir.mkdir(parents=True, exist_ok=True)
        out = modeled_dir / "cluster_assignments.parquet"
        assignments.to_parquet(out, engine="pyarrow", index=False)
        print(f"   ✅ cluster_assignments: {len(assignments)} rows → {out.name}")

    return assignments, summary
