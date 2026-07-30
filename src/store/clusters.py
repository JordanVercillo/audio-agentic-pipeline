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
from .models import ArtistProfile, ClusterModel, TrackCluster, utcnow

logger = logging.getLogger(__name__)

_MIN_TRACKS = 8       # below this a song model is noise, not signal
_MIN_ARTISTS = 4
_MIN_FEATURES = 3

# A clearly-broken extraction reads tempo 0 and silence — mirrors the mart's
# feature_valid gate (semantic._MIN_VALID_TEMPO). Excluded from TRAINING so a
# dead row can't define a centroid or skew the scaler / an artist's mean; the
# row still lives in the cache for the D-52 re-extraction.
_MIN_VALID_TEMPO_BPM = 1.0


def _drop_broken(feats: dict[str, dict]) -> dict[str, dict]:
    """Exclude only explicitly-broken extractions (tempo present and ≤ the
    floor); rows missing tempo entirely are left to the existing _complete gate."""
    return {tid: f for tid, f in feats.items()
            if not (isinstance(f.get("tempo_bpm"), (int, float))
                    and f["tempo_bpm"] <= _MIN_VALID_TEMPO_BPM)}


def _drop_twins(feats: dict[str, dict], excluded: set[str]) -> dict[str, dict]:
    """O3b: flagged duplicates sit out of TRAINING — the same recording twice
    would double-weight a centroid (11 analyzed twins rode the last retrain).
    B2: source-unvalidated tracks sit out too — callers pass
    `cache.excluded_from_aggregates()`, the one shared population filter."""
    return {tid: f for tid, f in feats.items() if tid not in excluded}


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
    feats = _drop_twins(_drop_broken(cache.all_features()),
                        cache.excluded_from_aggregates())
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
                             centroids=centroids, labels=names, label_dims=dims,
                             # D-62: the growth denominator, stamped at fit time.
                             # Counting TrackCluster rows later would be wrong —
                             # online assign_track inflates them.
                             n_trained=len(ids))
        s.add(model)
        s.flush()  # get model.id
        for i, tid in enumerate(ids):
            s.merge(TrackCluster(
                spotify_track_id=tid, model_id=model.id, cluster_id=int(labels[i]),
                map_x=float(xy[i][0]) if xy is not None else None,
                map_y=float(xy[i][1]) if xy is not None else None))
        s.commit()
        model_id = model.id
    promoted = _promote_if_first(cache, "song", model_id)
    return {"model_id": model_id, "k": k, "silhouette": round(silhouette, 3),
            "labels": names, "n_tracks": len(ids), "promoted": promoted}


def train_artist_clusters(cache: FeatureCache, *, k_range: tuple[int, int] = (2, 5),
                          ) -> Optional[dict[str, Any]]:
    """Cluster artists by their acoustic centroid (mean of their cached tracks)."""
    feats = _drop_twins(_drop_broken(cache.all_features()),
                        cache.excluded_from_aggregates())
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
    promoted = _promote_if_first(cache, "artist", model_id)
    return {"model_id": model_id, "k": k, "silhouette": round(silhouette, 3),
            "labels": names, "n_artists": len(artists), "promoted": promoted}


# ── K3: cluster-description plumbing ────────────────────────────────────────
def cluster_description_inputs(cache: FeatureCache, model: ClusterModel) -> list[dict]:
    """The describe_cluster() input dicts for a trained model — canonical label
    + the K3a dims + honest coverage. A pre-K3a model (label_dims None) gets
    dims=[], so the caller degrades to the name-only template."""
    assigns = track_assignments(cache, model.id)
    counts: dict[int, int] = {}
    for a in assigns.values():
        cid = int(a["cluster_id"])
        counts[cid] = counts.get(cid, 0) + 1
    dims_map = getattr(model, "label_dims", None) or {}
    out = [{"cluster_id": cid, "label": label,
            "dims": dims_map.get(cid) or [],
            "coverage": {"n_assigned": counts.get(int(cid), 0),
                         "n_corpus": len(assigns)}}
           for cid, label in (model.labels or {}).items()]
    return sorted(out, key=lambda c: int(c["cluster_id"]))


def save_descriptions(cache: FeatureCache, model_id: int,
                      descriptions: dict[str, dict]) -> bool:
    """Persist {"cid": {text, source, prompt_version}} onto the model row —
    the single write path for scripts/describe_clusters.py."""
    with cache._Session() as s:
        m = s.get(ClusterModel, model_id)
        if m is None:
            return False
        m.descriptions = descriptions
        s.commit()
    return True


# ── reads + online assignment ───────────────────────────────────────────────
def latest_model(cache: FeatureCache, kind: str) -> Optional[ClusterModel]:
    """The model currently SERVING — promoted only (D-62).

    Was `ORDER BY id DESC`, i.e. "whatever was trained last". That is what made
    training and promotion the same event, so a retrain could not happen
    without immediately moving every visitor-facing number. Pre-D-62 rows are
    back-promoted once by `FeatureCache._backfill_promoted_at`.
    """
    with cache._Session() as s:
        return s.execute(
            select(ClusterModel)
            .where(ClusterModel.kind == kind,
                   ClusterModel.promoted_at.isnot(None))
            .order_by(ClusterModel.promoted_at.desc(), ClusterModel.id.desc())
            .limit(1)
        ).scalars().first()


def newest_model(cache: FeatureCache, kind: str) -> Optional[ClusterModel]:
    """The most recently TRAINED model, promoted or not — the promotion queue."""
    with cache._Session() as s:
        return s.execute(
            select(ClusterModel).where(ClusterModel.kind == kind)
            .order_by(ClusterModel.id.desc()).limit(1)
        ).scalars().first()


# ── D-62: identity matching ─────────────────────────────────────────────────
# Auto-promote ONLY an identity-stable retrain. Pinned by the owner
# 2026-07-29: same k, every new centroid matches an old one at cosine >= this,
# and the matched pair's label words are byte-identical.
IDENTITY_COSINE_MIN = 0.90


def _centroids_in_common_space(old: ClusterModel, new: ClusterModel) -> Optional[np.ndarray]:
    """Old centroids expressed in the NEW model's scaled space, or None.

    Centroids are stored scaled, and each model scales against its own
    population — so the raw coordinates are not comparable between fits. We
    un-scale with the old model's stats and re-scale with the new model's, which
    puts both sets in one space. Returns None when the feature contract itself
    changed, because then no comparison is meaningful (that is
    FEATURE_CONTRACT_DRIFT, a different finding).
    """
    if list(old.feature_cols) != list(new.feature_cols):
        return None
    o_mean, o_std = np.array(old.scaler_mean), np.array(old.scaler_std)
    n_mean, n_std = np.array(new.scaler_mean), np.array(new.scaler_std)
    n_std = np.where(n_std == 0, 1.0, n_std)
    raw = np.array(old.centroids) * o_std + o_mean          # -> raw units
    return (raw - n_mean) / n_std                            # -> new scaled space


def match_identity(old: ClusterModel, new: ClusterModel) -> Optional[dict[str, int]]:
    """{new_cluster_id: old_cluster_id} if `new` is identity-stable, else None.

    Greedy best-cosine with no double-use: two new clusters may not both claim
    the same old identity, because that is precisely the "the buckets actually
    changed" case we must NOT auto-promote.
    """
    if old.k != new.k:
        return None
    old_pts = _centroids_in_common_space(old, new)
    if old_pts is None:
        return None
    new_pts = np.array(new.centroids)

    pairs: list[tuple[float, int, int]] = []
    for ni, nv in enumerate(new_pts):
        for oi, ov in enumerate(old_pts):
            denom = float(np.linalg.norm(nv) * np.linalg.norm(ov))
            cos = float(np.dot(nv, ov) / denom) if denom else -1.0
            pairs.append((cos, ni, oi))
    pairs.sort(reverse=True)

    mapping: dict[str, int] = {}
    used_old: set[int] = set()
    for cos, ni, oi in pairs:
        if str(ni) in mapping or oi in used_old:
            continue
        if cos < IDENTITY_COSINE_MIN:
            continue
        mapping[str(ni)] = oi
        used_old.add(oi)

    if len(mapping) != new.k:
        return None
    # The words are the visitor-facing identity; a centroid can drift within
    # tolerance and still get renamed, and a renamed bucket is a new bucket.
    for ni, oi in mapping.items():
        if str(new.labels.get(str(ni))) != str(old.labels.get(str(oi))):
            return None
    return mapping


def promote_model(cache: FeatureCache, model_id: int, *,
                  identity_map: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """Make a trained model the serving one, remapping ids through identity_map.

    Remapping rewrites cluster_id (and the labels/label_dims/descriptions keyed
    on it) so that cluster 0 keeps meaning the same SOUND across the promotion.
    Without it, `cluster_color(0)` and the archetype's home bucket silently
    point at a different bucket after every retrain.
    """
    with cache._Session() as s:
        model = s.get(ClusterModel, model_id)
        if model is None:
            raise ValueError(f"no cluster model with id {model_id}")

        if identity_map:
            inv = {int(new): int(old) for new, old in identity_map.items()}
            for row in s.execute(select(TrackCluster).where(
                    TrackCluster.model_id == model_id)).scalars().all():
                row.cluster_id = inv.get(int(row.cluster_id), int(row.cluster_id))
            for attr in ("labels", "label_dims", "descriptions"):
                cur = getattr(model, attr, None)
                if cur:
                    setattr(model, attr, {str(inv.get(int(k), int(k))): v
                                          for k, v in cur.items()})
            model.identity_map = {str(k): v for k, v in identity_map.items()}

        model.promoted_at = utcnow()
        s.commit()
        return {"model_id": model_id, "k": model.k,
                "remapped": bool(identity_map),
                "labels": dict(model.labels)}


def _promote_if_first(cache: FeatureCache, kind: str, model_id: int) -> bool:
    """Bootstrap: the FIRST model of a kind serves immediately.

    D-62 holds a retrain back because promotion changes an identity a visitor
    has already seen. When nothing is promoted yet there is no such identity —
    holding would just render the surface blank and call it caution. Returns
    True if it promoted.
    """
    with cache._Session() as s:
        existing = s.execute(
            select(ClusterModel.id).where(ClusterModel.kind == kind,
                                          ClusterModel.promoted_at.isnot(None))
            .limit(1)).first()
    if existing:
        return False
    promote_model(cache, model_id)
    logger.info("%s model %d promoted on bootstrap (no prior model)", kind, model_id)
    return True


def freshness(cache: FeatureCache, kind: str = "song") -> dict[str, Any]:
    """Why (or whether) `kind`'s serving model is due a retrain — D-62 triggers.

    Read-only and cheap: this runs in the post-drain chain, which must never
    pay for a decision it might not act on. Deliberately NOT a trigger:
    silhouette decline. It is a CONSEQUENCE of corpus growth (measured live
    0.176 -> 0.148 as the corpus grew), so gating on it would freeze the model
    at its smallest, most flattering population forever.
    """
    served = latest_model(cache, kind)
    population = set(cache.analyzed_ids()) - set(cache.excluded_from_aggregates())
    n_pop = len(population)
    out: dict[str, Any] = {"kind": kind, "n_population": n_pop,
                           "model_id": None, "n_trained": None,
                           "coverage": None, "growth_ratio": None,
                           "reasons": [], "stale": False,
                           "descriptions_missing": False}
    if served is None:
        out["reasons"].append("no promoted model")
        out["stale"] = n_pop >= _MIN_TRACKS
        return out

    assigned = set(track_assignments(cache, served.id))
    coverage = len(assigned & population) / n_pop if n_pop else 1.0
    n_trained = served.n_trained or 0
    out.update(model_id=served.id, n_trained=n_trained or None,
               coverage=round(coverage, 4))

    if coverage < 0.95:
        out["reasons"].append(f"coverage {coverage:.1%} < 95%")
    if n_trained:
        ratio = n_pop / n_trained
        out["growth_ratio"] = round(ratio, 3)
        if ratio >= 1.25:
            out["reasons"].append(f"corpus grew {ratio:.2f}x since training")
    if list(served.feature_cols) != _current_feature_cols(cache):
        out["reasons"].append("feature contract changed")
    if not (served.descriptions or {}):
        out["descriptions_missing"] = True

    out["stale"] = bool(out["reasons"])
    return out


def _current_feature_cols(cache: FeatureCache) -> list[str]:
    """The columns a retrain WOULD pick today — the contract-drift comparand."""
    feats = _drop_twins(_drop_broken(cache.all_features()),
                        cache.excluded_from_aggregates())
    if len(feats) < _MIN_TRACKS:
        return []
    return select_feature_cols([feats[i] for i in feats])


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
