"""D-62 freshness tests — the regression class, not the incident.

The condition these guard was fixed BY HAND in session 50 (coverage 39% ->
99.7%) and had silently regressed to 36.7% seven days later, with both audits
green throughout, because the fix was a command and the only cluster-coverage
check bounded `n_assigned` from ABOVE only. A guard with one side is half a
guard, so these assert the side that growth actually approaches from.

Synthetic only (ground rule 5).
"""
from __future__ import annotations

import numpy as np
import pytest

from . import clusters as cl
from .cache import FeatureCache
from .models import ClusterModel, TrackCluster

_COLS = ["tempo_bpm", "rms_mean", "spectral_centroid_mean", "zcr_mean",
         "harmonic_ratio", "onset_strength_mean"]


# PLAUSIBLE units, not abstract blobs: `_drop_broken` discards tempo_bpm < 1.0
# as a failed extraction, so a fixture centred on -2.0 loses half its rows
# before training and every count assertion drifts. (Cost me three failing
# tests; the fixture was wrong, not the code.)
_HI = {"tempo_bpm": 150.0, "rms_mean": 0.50, "spectral_centroid_mean": 3000.0,
       "zcr_mean": 0.15, "harmonic_ratio": 0.30, "onset_strength_mean": 2.0}
_LO = {"tempo_bpm": 90.0, "rms_mean": 0.15, "spectral_centroid_mean": 1200.0,
       "zcr_mean": 0.04, "harmonic_ratio": 0.70, "onset_strength_mean": 0.8}


def _feat(seed: int, hi: bool) -> dict:
    """Two well-separated, physically plausible blobs."""
    rng = np.random.default_rng(seed)
    base = _HI if hi else _LO
    return {c: float(v * (1.0 + rng.normal(0, 0.02))) for c, v in base.items()}


@pytest.fixture()
def cache(tmp_path):
    c = FeatureCache(f"sqlite:///{tmp_path/'f.db'}")
    for i in range(20):
        tid = f"trk{i:03d}"
        c.upsert(tid, _feat(i, hi=i % 2 == 0))
    return c


def _grow(cache: FeatureCache, start: int, n: int) -> None:
    for i in range(start, start + n):
        cache.upsert(f"trk{i:03d}", _feat(i, hi=i % 2 == 0))


# ── the promotion split ─────────────────────────────────────────────────────
def test_training_alone_does_not_change_what_is_served(cache):
    """The whole point of D-62: a retrain must be able to land without moving a
    single visitor-facing number until someone promotes it."""
    first = cl.train_song_clusters(cache)
    assert first is not None
    cl.promote_model(cache, first["model_id"])
    served_before = cl.latest_model(cache, "song").id

    _grow(cache, 20, 20)
    second = cl.train_song_clusters(cache)
    assert second["model_id"] != first["model_id"]

    assert cl.latest_model(cache, "song").id == served_before, \
        "an unpromoted retrain changed the serving model"
    assert cl.newest_model(cache, "song").id == second["model_id"]


def test_n_trained_is_stamped_and_is_not_the_assignment_count(cache):
    r = cl.train_song_clusters(cache)
    m = cl.newest_model(cache, "song")
    assert m.n_trained == r["n_tracks"] == 20
    # Online assignment inflates TrackCluster rows; the denominator must not move.
    cl.promote_model(cache, m.id)
    _grow(cache, 20, 5)
    cl.assign_track(cache, m, "trk020", _feat(20, hi=True))
    assert cl.newest_model(cache, "song").n_trained == 20


# ── the trigger that today's live data trips ────────────────────────────────
def test_coverage_flag_fires_when_corpus_outgrows_model(cache):
    """Train on 20, add 20 more, never retrain: coverage must read stale.

    This makes the live 36.7%-and-green condition structurally impossible.
    """
    r = cl.train_song_clusters(cache)
    cl.promote_model(cache, r["model_id"])
    assert cl.freshness(cache, "song")["stale"] is False

    _grow(cache, 20, 20)
    f = cl.freshness(cache, "song")
    assert f["stale"] is True
    assert f["coverage"] < 0.95
    assert any("coverage" in x for x in f["reasons"])
    assert any("grew" in x for x in f["reasons"])   # growth ratio 2.0x


def test_growth_retrain_is_not_blocked_by_lower_silhouette(cache):
    """Silhouette DROPS as a corpus grows (measured live 0.176 -> 0.148).

    Encoded so nobody 'fixes' freshness into a gate that would freeze the model
    at its smallest, most flattering population forever.
    """
    r = cl.train_song_clusters(cache)
    cl.promote_model(cache, r["model_id"])
    # Fill the gap between the two blobs: genuinely less separable.
    for i in range(100, 140):
        rng = np.random.default_rng(i)
        mid = {c: float((_HI[c] + _LO[c]) / 2 * (1.0 + rng.normal(0, 0.15)))
               for c in _COLS}
        cache.upsert(f"trk{i:03d}", mid)
    f = cl.freshness(cache, "song")
    assert f["stale"] is True, "growth must still trigger a retrain"
    assert "silhouette" not in " ".join(f["reasons"]).lower(), \
        "silhouette must never appear as a staleness REASON"


# ── the trap a naive auto-promote would hit ─────────────────────────────────
def test_promotion_remap_preserves_cluster_identity(cache):
    """KMeans does not preserve label order. Promoting without remapping
    silently inverts the legend colours and the archetype's home bucket."""
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    cl.promote_model(cache, old.id)
    old_label_of_0 = old.labels["0"]

    # A retrain whose clusters are the SAME sounds in REVERSED slots — exactly
    # what a re-fit produces when KMeans initialises differently. k-agnostic.
    perm = list(reversed(range(old.k)))          # new i holds old perm[i]
    with cache._Session() as s:
        swapped = ClusterModel(
            kind="song", k=old.k, silhouette=old.silhouette,
            feature_cols=list(old.feature_cols),
            scaler_mean=list(old.scaler_mean), scaler_std=list(old.scaler_std),
            centroids=[old.centroids[perm[i]] for i in range(old.k)],
            labels={str(i): old.labels[str(perm[i])] for i in range(old.k)},
            label_dims=None, n_trained=old.n_trained)
        s.add(swapped)
        s.commit()
        new_id, new_obj = swapped.id, swapped

    mapping = cl.match_identity(old, new_obj)
    assert mapping == {str(i): perm[i] for i in range(old.k)}, \
        f"identity match failed: {mapping}"

    cl.promote_model(cache, new_id, identity_map=mapping)
    promoted = cl.latest_model(cache, "song")
    assert promoted.id == new_id
    assert promoted.labels["0"] == old_label_of_0, \
        "cluster 0 changed meaning across a promotion"


def test_identity_match_refuses_when_k_changes(cache):
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    with cache._Session() as s:
        other = ClusterModel(
            kind="song", k=old.k + 1, silhouette=0.1,
            feature_cols=list(old.feature_cols),
            scaler_mean=list(old.scaler_mean), scaler_std=list(old.scaler_std),
            centroids=list(old.centroids) + [list(old.centroids[0])],
            labels={**old.labels, str(old.k): "New Bucket"}, n_trained=1)
        s.add(other)
        s.commit()
        obj = other
    assert cl.match_identity(old, obj) is None


def test_identity_match_refuses_when_a_label_is_renamed(cache):
    """A centroid can drift within tolerance and still be renamed. A renamed
    bucket is a NEW bucket to the visitor, so it needs ratification."""
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    with cache._Session() as s:
        renamed = ClusterModel(
            kind="song", k=old.k, silhouette=old.silhouette,
            feature_cols=list(old.feature_cols),
            scaler_mean=list(old.scaler_mean), scaler_std=list(old.scaler_std),
            centroids=list(old.centroids),
            labels={k: f"{v} Remix" for k, v in old.labels.items()},
            n_trained=old.n_trained)
        s.add(renamed)
        s.commit()
        obj = renamed
    assert cl.match_identity(old, obj) is None


def test_identity_match_refuses_on_feature_contract_change(cache):
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    with cache._Session() as s:
        drifted = ClusterModel(
            kind="song", k=old.k, silhouette=old.silhouette,
            feature_cols=list(old.feature_cols)[:-1],      # one column dropped
            scaler_mean=list(old.scaler_mean)[:-1], scaler_std=list(old.scaler_std)[:-1],
            centroids=[c[:-1] for c in old.centroids],
            labels=dict(old.labels), n_trained=old.n_trained)
        s.add(drifted)
        s.commit()
        obj = drifted
    assert cl.match_identity(old, obj) is None


# ── the migration that must not blank a live surface ────────────────────────
def _legacy_db(tmp_path, *, forget_migration: bool):
    """A DB with one unpromoted model, optionally with the migration marker
    removed so it looks genuinely pre-D-62 rather than merely rolled back."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path/'legacy.db'}"
    c = FeatureCache(url)
    for i in range(20):
        c.upsert(f"trk{i:03d}", _feat(i, hi=i % 2 == 0))
    r = cl.train_song_clusters(c)
    with c._Session() as s:
        s.get(ClusterModel, r["model_id"]).promoted_at = None
        s.commit()
    if forget_migration:
        with c.engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_migrations "
                              "WHERE name = 'd62_backfill_promoted_at'"))
    c.close()
    return url, r["model_id"]


def test_pre_d62_model_is_back_promoted_so_nothing_goes_dark(tmp_path):
    """A model written before promoted_at existed must keep serving."""
    url, model_id = _legacy_db(tmp_path, forget_migration=True)
    served = cl.latest_model(FeatureCache(url), "song")   # boot runs the backfill
    assert served is not None, "the migration took the serving model dark"
    assert served.id == model_id


def test_backfill_is_one_shot_so_a_rollback_is_not_undone(tmp_path):
    """Clearing promoted_at must STAY cleared once the migration has run.

    Director review, 2026-07-31: this backfill ran on every `FeatureCache()`
    construction, and the webapp builds one per request. That made it not a
    migration but a standing rule — "if nothing is promoted, promote the
    newest" — so rolling a bad promotion back auto-promoted the newest
    UNREVIEWED candidate on the very next HTTP request, inverting the entire
    premise of D-62 (a human ratifies what visitors see).
    """
    url, _ = _legacy_db(tmp_path, forget_migration=False)
    assert cl.latest_model(FeatureCache(url), "song") is None, (
        "the rollback was undone at boot — D-62's human-in-the-loop is bypassed")


def test_descriptions_missing_is_reported(cache):
    r = cl.train_song_clusters(cache)
    cl.promote_model(cache, r["model_id"])
    assert cl.freshness(cache, "song")["descriptions_missing"] is True
    cl.save_descriptions(cache, r["model_id"],
                         {"0": {"text": "x", "source": "template"},
                          "1": {"text": "y", "source": "template"}})
    assert cl.freshness(cache, "song")["descriptions_missing"] is False


def test_training_does_not_destroy_the_serving_models_assignments(cache):
    """The composite-key fix. `spotify_track_id` alone was the primary key, so
    every training run's merge OVERWROTE the serving model's rows — measured
    live, training took the served model from 700 assignments to 4.

    That is not a cosmetic bug: it makes D-62's premise false, because training
    alone would silently gut the coverage of whatever is being served.
    """
    first = cl.train_song_clusters(cache)
    cl.promote_model(cache, first["model_id"])
    before = len(cl.track_assignments(cache, first["model_id"]))
    assert before > 0

    _grow(cache, 20, 20)
    second = cl.train_song_clusters(cache)
    assert second["model_id"] != first["model_id"]

    after = len(cl.track_assignments(cache, first["model_id"]))
    assert after == before, (
        f"training a new model destroyed the serving model's assignments "
        f"({before} -> {after})")
    assert len(cl.track_assignments(cache, second["model_id"])) >= before
    # And the served model's coverage must be untouched by a mere retrain.
    assert cl.latest_model(cache, "song").id == first["model_id"]


def test_promotion_keeps_centroids_and_labels_in_ONE_id_space(cache):
    """The half `test_promotion_remap_preserves_cluster_identity` didn't check.

    `centroids` is a LIST INDEXED BY cluster id; labels/label_dims/descriptions
    are dicts KEYED by it. The first promote_model remapped the keyed ones and
    left the indexed one, so `nearest_cluster` answered in the new fit's space
    while every stored row had moved to the old one. Measured on live model 13
    before the fix: 1,894 of 1,894 assignments disagreed with the model's own
    rule — and the suite, the audit and the browser all read green.
    """
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    cl.promote_model(cache, old.id)

    perm = list(reversed(range(old.k)))
    with cache._Session() as s:
        swapped = ClusterModel(
            kind="song", k=old.k, silhouette=old.silhouette,
            feature_cols=list(old.feature_cols),
            scaler_mean=list(old.scaler_mean), scaler_std=list(old.scaler_std),
            centroids=[old.centroids[perm[i]] for i in range(old.k)],
            labels={str(i): old.labels[str(perm[i])] for i in range(old.k)},
            n_trained=old.n_trained)
        s.add(swapped)
        s.commit()
        new_id = swapped.id
        # give the new model its own assignments, as a real training run would
        for tid, a in cl.track_assignments(cache, old.id).items():
            s.merge(TrackCluster(spotify_track_id=tid, model_id=new_id,
                                 cluster_id=perm[int(a["cluster_id"])]))
        s.commit()

    mapping = cl.match_identity(old, cl.newest_model(cache, "song"))
    assert mapping, "the permuted refit should be identity-stable"
    cl.promote_model(cache, new_id, identity_map=mapping)

    served = cl.latest_model(cache, "song")
    feats = cache.feature_columns(list(served.feature_cols))
    disagree = [
        tid for tid, a in cl.track_assignments(cache, new_id).items()
        if (nc := cl.nearest_cluster(served, feats[tid])) is not None
        and nc != a["cluster_id"]]
    assert not disagree, (
        f"{len(disagree)} stored assignment(s) disagree with the promoted "
        f"model's own nearest-centroid rule — centroids and ids are in "
        f"different spaces")


def test_promoting_an_already_remapped_model_is_refused(cache):
    """Rollback re-promotes a model that already carries a map, and the CLI
    computes a FRESH map against the current servant — applying it on top
    inverts k=2 straight back."""
    cl.train_song_clusters(cache)
    old = cl.newest_model(cache, "song")
    cl.promote_model(cache, old.id)
    perm = list(reversed(range(old.k)))
    with cache._Session() as s:
        m2 = ClusterModel(
            kind="song", k=old.k, silhouette=old.silhouette,
            feature_cols=list(old.feature_cols),
            scaler_mean=list(old.scaler_mean), scaler_std=list(old.scaler_std),
            centroids=[old.centroids[perm[i]] for i in range(old.k)],
            labels={str(i): old.labels[str(perm[i])] for i in range(old.k)},
            n_trained=old.n_trained)
        s.add(m2)
        s.commit()
        mid = m2.id
    mapping = cl.match_identity(old, cl.newest_model(cache, "song"))
    cl.promote_model(cache, mid, identity_map=mapping)
    with pytest.raises(ValueError, match="already remapped"):
        cl.promote_model(cache, mid, identity_map=mapping)
