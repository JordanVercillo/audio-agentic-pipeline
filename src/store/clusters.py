"""
clusters.py — population clustering over the feature cache (APP_SPEC Epic C).

Trains versioned KMeans models over ALL cached tracks (songs) and over per-artist
acoustic centroids (artists), names each cluster by its most distinguishing
acoustic dimensions (the journal-#9 trick, shared vocabulary with
`analysis/clustering.py`), and persists everything to the cache DB so the webapp
can assign a NEW track online (nearest centroid) without retraining.

Deterministic: fixed random_state, silhouette-chosen k. 2-D map coordinates via
PCA by default (fast, deterministic); UMAP optionally when the population is
large enough. Training runs on the PC (scikit-learn — right-sized, D-16); the
Spark clustering job is the documented at-scale path.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..analysis.clustering import _CHARACTER_DIMS, VECTOR_77_COLUMNS, cluster_tracks
from .cache import FeatureCache
from .models import ArtistProfile, ClusterModel, TrackCluster

logger = logging.getLogger(__name__)

_MIN_TRACKS = 8       # below this a song model is noise, not signal
_MIN_ARTISTS = 4
_MIN_FEATURES = 3


# ── feature selection & scaling ─────────────────────────────────────────────
def _has(row: dict, col: str) -> bool:
    v = row.get(col)
    return isinstance(v, (int, float)) and v is not None


def select_feature_cols(rows: list[dict], min_coverage: float = 0.9) -> list[str]:
    """Vector columns present (non-null) in ≥``min_coverage`` of rows — prefer the
    frozen 77-dim contract; fall back to shared numeric features (synthetic corpora).

    Coverage, not intersection: a single sparse row (e.g. a track whose audio was
    never acquired) must not poison every column for the whole population.
    """
    n = len(rows)

    def covered(cols: list[str]) -> list[str]:
        return [c for c in cols if sum(_has(r, c) for r in rows) >= min_coverage * n]

    cols = covered(list(VECTOR_77_COLUMNS))
    if len(cols) >= _MIN_FEATURES:
        return cols
    numeric = sorted({k for r in rows for k, v in r.items()
                      if isinstance(v, (int, float)) and v is not None})
    return covered(numeric)


def _complete(ids: list[str], rows: list[dict], cols: list[str],
              ) -> tuple[list[str], list[dict]]:
    """Keep only rows that have every selected column (sparse rows sit out this
    training run; they get assigned once their features are extracted)."""
    pairs = [(i, r) for i, r in zip(ids, rows, strict=True)
             if all(_has(r, c) for c in cols)]
    return [i for i, _ in pairs], [r for _, r in pairs]


def _scale(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Standardize + L2-normalize (the prepare_matrix recipe). Returns (X, mean, std)."""
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    X = (matrix - mean) / std
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (X / norms).astype(np.float32), mean, std


def _apply_scale(vec: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    x = (vec - mean) / std
    n = np.linalg.norm(x)
    return (x / n if n else x).astype(np.float32)


def _label_dims(member: pd.DataFrame, corpus: pd.DataFrame, top_n: int = 2,
                ) -> list[dict]:
    """Ranked ``[{feature, word, z}]`` for the top-|z| interpretable dims — the
    exact evidence that names the cluster. K3 persists this so generated
    descriptions can be graded against the dims that produced the name
    (the mart's perceptual means are NOT these columns)."""
    scored: list[tuple[float, str, str, float]] = []
    for col, hi, lo in _CHARACTER_DIMS:
        if col not in corpus.columns:
            continue
        std = float(corpus[col].std())
        if std == 0 or np.isnan(std):
            continue
        z = (float(member[col].mean()) - float(corpus[col].mean())) / std
        # tuple order keeps the frozen tie-break: (|z|, word) sorted reverse
        scored.append((abs(z), hi if z > 0 else lo, col, z))
    scored.sort(reverse=True)
    return [{"feature": col, "word": word, "z": round(float(z), 4)}
            for _, word, col, z in scored[:top_n]]


def _label_cluster(member: pd.DataFrame, corpus: pd.DataFrame, top_n: int = 2) -> str:
    """Name a cluster by top-|z| interpretable dims (shared _CHARACTER_DIMS words)."""
    dims = _label_dims(member, corpus, top_n)
    return " · ".join(d["word"] for d in dims) if dims else "Mixed"


def _map_coords(X: np.ndarray, method: str = "pca") -> Optional[np.ndarray]:
    """2-D map coordinates: PCA (deterministic default) or UMAP for larger corpora."""
    if X.shape[0] < 3:
        return None
    if method == "umap" and X.shape[0] >= 10:
        try:
            from umap import UMAP
            return UMAP(n_components=2, random_state=42,
                        n_neighbors=min(15, X.shape[0] - 1)).fit_transform(X)
        except Exception as exc:  # noqa: BLE001 — fall back rather than fail training
            logger.warning("UMAP failed (%s) — falling back to PCA", exc)
    from sklearn.decomposition import PCA
    return PCA(n_components=2, random_state=42).fit_transform(X)


# ── training ────────────────────────────────────────────────────────────────
def train_song_clusters(cache: FeatureCache, *, k_range: tuple[int, int] = (2, 6),
                        coords: str = "pca") -> Optional[dict[str, Any]]:
    """Cluster ALL cached tracks; persist the model + per-track assignments."""
    feats = cache.all_features()
    if len(feats) < _MIN_TRACKS:
        logger.info("song clustering skipped: %d < %d cached tracks", len(feats), _MIN_TRACKS)
        return None
    ids = list(feats)
    rows = [feats[i] for i in ids]
    cols = select_feature_cols(rows)
    if len(cols) < _MIN_FEATURES:
        return None
    ids, rows = _complete(ids, rows, cols)
    if len(ids) < _MIN_TRACKS:
        return None

    raw = np.array([[float(r[c]) for c in cols] for r in rows])
    X, mean, std = _scale(raw)
    labels, k, silhouette = cluster_tracks(X, k_range=(k_range[0], min(k_range[1], len(ids) - 1)))

    corpus_df = pd.DataFrame(rows)
    dims = {str(c): _label_dims(corpus_df[labels == c], corpus_df)
            for c in range(k)}
    names = {c: (" · ".join(d["word"] for d in ds) if ds else "Mixed")
             for c, ds in dims.items()}
    centroids = [X[labels == c].mean(axis=0).tolist() for c in range(k)]
    xy = _map_coords(X, method=coords)

    with cache._Session() as s:
        model = ClusterModel(kind="song", k=k, silhouette=silhouette, feature_cols=cols,
                             scaler_mean=mean.tolist(), scaler_std=std.tolist(),
                             centroids=centroids, labels=names, label_dims=dims)
        s.add(model)
        s.flush()  # get model.id
        for i, tid in enumerate(ids):
            s.merge(TrackCluster(
                spotify_track_id=tid, model_id=model.id, cluster_id=int(labels[i]),
                map_x=float(xy[i][0]) if xy is not None else None,
                map_y=float(xy[i][1]) if xy is not None else None))
        s.commit()
        model_id = model.id
    return {"model_id": model_id, "k": k, "silhouette": round(silhouette, 3),
            "labels": names, "n_tracks": len(ids)}


def train_artist_clusters(cache: FeatureCache, *, k_range: tuple[int, int] = (2, 5),
                          ) -> Optional[dict[str, Any]]:
    """Cluster artists by their acoustic centroid (mean of their cached tracks)."""
    feats = cache.all_features()
    meta = cache.all_meta()
    by_artist: dict[str, list[dict]] = {}
    for tid, f in feats.items():
        names = (meta.get(tid) or {}).get("artist_names") or ""
        primary = names.split(",")[0].strip()
        if primary:
            by_artist.setdefault(primary, []).append(f)
    if len(by_artist) < _MIN_ARTISTS:
        logger.info("artist clustering skipped: %d < %d artists", len(by_artist), _MIN_ARTISTS)
        return None

    sample = [f for fs in by_artist.values() for f in fs]
    cols = select_feature_cols(sample)
    if len(cols) < _MIN_FEATURES:
        return None
    # Sparse tracks sit out; artists with no complete tracks sit out entirely.
    by_artist = {a: [f for f in fs if all(_has(f, c) for c in cols)]
                 for a, fs in by_artist.items()}
    by_artist = {a: fs for a, fs in by_artist.items() if fs}
    if len(by_artist) < _MIN_ARTISTS:
        return None
    artists = sorted(by_artist)
    raw = np.array([[float(np.mean([f[c] for f in by_artist[a]])) for c in cols]
                    for a in artists])
    X, mean, std = _scale(raw)
    labels, k, silhouette = cluster_tracks(
        X, k_range=(k_range[0], min(k_range[1], len(artists) - 1)))

    centroid_df = pd.DataFrame(raw, columns=cols)
    dims = {str(c): _label_dims(centroid_df[labels == c], centroid_df)
            for c in range(k)}
    names = {c: (" · ".join(d["word"] for d in ds) if ds else "Mixed")
             for c, ds in dims.items()}
    centroids = [X[labels == c].mean(axis=0).tolist() for c in range(k)]

    with cache._Session() as s:
        model = ClusterModel(kind="artist", k=k, silhouette=silhouette, feature_cols=cols,
                             scaler_mean=mean.tolist(), scaler_std=std.tolist(),
                             centroids=centroids, labels=names, label_dims=dims)
        s.add(model)
        s.flush()
        for i, a in enumerate(artists):
            s.merge(ArtistProfile(artist_key=a, track_count=len(by_artist[a]),
                                  model_id=model.id, cluster_id=int(labels[i])))
        s.commit()
        model_id = model.id
    return {"model_id": model_id, "k": k, "silhouette": round(silhouette, 3),
            "labels": names, "n_artists": len(artists)}


# ── reads + online assignment ───────────────────────────────────────────────
def latest_model(cache: FeatureCache, kind: str) -> Optional[ClusterModel]:
    with cache._Session() as s:
        return s.execute(
            select(ClusterModel).where(ClusterModel.kind == kind)
            .order_by(ClusterModel.id.desc()).limit(1)
        ).scalars().first()


def assign_track(cache: FeatureCache, model: ClusterModel, track_id: str,
                 features: dict) -> Optional[int]:
    """Nearest-centroid assignment for a track the model hasn't seen; persisted."""
    try:
        vec = np.array([float(features[c]) for c in model.feature_cols])
    except (KeyError, TypeError, ValueError):
        return None  # missing features → unassignable until next training run
    x = _apply_scale(vec, np.array(model.scaler_mean), np.array(model.scaler_std))
    dists = [float(np.linalg.norm(x - np.array(c))) for c in model.centroids]
    cluster_id = int(np.argmin(dists))
    with cache._Session() as s:
        s.merge(TrackCluster(spotify_track_id=track_id, model_id=model.id,
                             cluster_id=cluster_id, map_x=None, map_y=None))
        s.commit()
    return cluster_id


def track_assignments(cache: FeatureCache, model_id: int) -> dict[str, dict]:
    """{track_id: {cluster_id, map_x, map_y}} for a model — the map population."""
    with cache._Session() as s:
        rows = s.execute(
            select(TrackCluster).where(TrackCluster.model_id == model_id)
        ).scalars().all()
    return {r.spotify_track_id: {"cluster_id": r.cluster_id,
                                 "map_x": r.map_x, "map_y": r.map_y} for r in rows}


def artist_buckets(cache: FeatureCache, model_id: int) -> dict[int, list[dict]]:
    """{cluster_id: [{artist, track_count}...]} sorted by track_count desc."""
    with cache._Session() as s:
        rows = s.execute(
            select(ArtistProfile).where(ArtistProfile.model_id == model_id)
        ).scalars().all()
    out: dict[int, list[dict]] = {}
    for r in sorted(rows, key=lambda r: -(r.track_count or 0)):
        out.setdefault(int(r.cluster_id), []).append(
            {"artist": r.artist_key, "track_count": r.track_count})
    return out
