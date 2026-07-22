"""
test_clusters.py — synthetic tests for population clustering (APP_SPEC Epic C).

Two well-separated acoustic blobs → training must find them, name them
differently, and assign a new unseen track to the right one. No real audio,
no network; PCA coords (deterministic, fast).
"""

from __future__ import annotations

import pytest

from .cache import FeatureCache
from .clusters import (
    artist_buckets,
    assign_track,
    latest_model,
    select_feature_cols,
    track_assignments,
    train_artist_clusters,
    train_song_clusters,
)


# Blob A: slow/quiet/dark/harmonic · Blob B: fast/loud/bright/percussive.
def _blob_a(i: float) -> dict:
    return {"tempo_bpm": 90 + i, "rms_mean": 0.10 + i / 100, "spectral_centroid_mean": 1500 + 10 * i,
            "zcr_mean": 0.03, "harmonic_ratio": 0.9, "onset_strength_mean": 1.0}


def _blob_b(i: float) -> dict:
    return {"tempo_bpm": 150 + i, "rms_mean": 0.30 + i / 100, "spectral_centroid_mean": 3200 + 10 * i,
            "zcr_mean": 0.09, "harmonic_ratio": 0.4, "onset_strength_mean": 3.0}


@pytest.fixture
def corpus(tmp_path):
    """12 tracks (6 per blob) across 6 artists (3 per blob), with metadata."""
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'cl.db'}")
    meta = []
    for i in range(6):
        a_id, b_id = f"a{i}", f"b{i}"
        cache.upsert(a_id, _blob_a(i))
        cache.upsert(b_id, _blob_b(i))
        meta.append({"spotify_track_id": a_id, "track_name": f"Slow {i}",
                     "artist_names": f"CalmArtist{i // 2}"})
        meta.append({"spotify_track_id": b_id, "track_name": f"Fast {i}",
                     "artist_names": f"LoudArtist{i // 2}"})
    cache.remember_meta(meta)
    return cache


def test_select_feature_cols_falls_back_to_shared_numeric(corpus):
    rows = list(corpus.all_features().values())
    cols = select_feature_cols(rows)
    assert "tempo_bpm" in cols and len(cols) >= 3


def test_train_song_clusters_finds_the_two_blobs(corpus):
    res = train_song_clusters(corpus, coords="pca")
    assert res is not None and res["k"] == 2 and res["silhouette"] > 0.5
    assert len(res["labels"]) == 2
    assert res["labels"]["0"] != res["labels"]["1"]  # named differently

    model = latest_model(corpus, "song")
    assigned = track_assignments(corpus, model.id)
    assert len(assigned) == 12
    # blob members share a cluster; the blobs differ
    a_clusters = {assigned[f"a{i}"]["cluster_id"] for i in range(6)}
    b_clusters = {assigned[f"b{i}"]["cluster_id"] for i in range(6)}
    assert len(a_clusters) == 1 and len(b_clusters) == 1 and a_clusters != b_clusters
    # map coords persisted
    assert assigned["a0"]["map_x"] is not None


def test_assign_track_online_nearest_centroid(corpus):
    train_song_clusters(corpus, coords="pca")
    model = latest_model(corpus, "song")
    assigned = track_assignments(corpus, model.id)
    b_cluster = assigned["b0"]["cluster_id"]
    # a brand-new fast/loud track must land in the fast blob
    cid = assign_track(corpus, model, "new_fast", _blob_b(2.5))
    assert cid == b_cluster
    assert track_assignments(corpus, model.id)["new_fast"]["cluster_id"] == b_cluster
    # a track missing the model's features is unassignable (not an error)
    assert assign_track(corpus, model, "sparse", {"tempo_bpm": 120}) is None


def test_label_dims_are_the_evidence_behind_the_name(corpus):
    # K3a: the persisted dims must reconstruct the label exactly — they are the
    # grounding substrate for generated descriptions (grounded_in_centroid).
    train_song_clusters(corpus, coords="pca")
    model = latest_model(corpus, "song")
    assert model.label_dims is not None
    assert set(model.label_dims) == set(model.labels)
    for cid, name in model.labels.items():
        dims = model.label_dims[cid]
        assert " · ".join(d["word"] for d in dims) == name  # dims ⇒ name, byte-exact
        for d in dims:
            assert set(d) == {"feature", "word", "z"}
            assert isinstance(d["z"], float) and d["z"] != 0
    # |z| ranking is descending — the first dim is the strongest evidence
    for dims in model.label_dims.values():
        zs = [abs(d["z"]) for d in dims]
        assert zs == sorted(zs, reverse=True)


def test_cluster_description_inputs_and_save_roundtrip(corpus):
    # K3d: the script's input assembly + single write path.
    from .clusters import cluster_description_inputs, save_descriptions
    train_song_clusters(corpus, coords="pca")
    model = latest_model(corpus, "song")
    inputs = cluster_description_inputs(corpus, model)
    assert [c["cluster_id"] for c in inputs] == sorted(model.labels)
    for c in inputs:
        assert c["label"] == model.labels[c["cluster_id"]]     # canonical, pinned
        assert c["dims"] == model.label_dims[c["cluster_id"]]  # the K3a evidence
        assert c["coverage"]["n_corpus"] == 12
        assert c["coverage"]["n_assigned"] == 6                # two even blobs
    descs = {c["cluster_id"]: {"text": f"d{c['cluster_id']}", "source": "fallback",
                               "prompt_version": "rtcros-cluster-v1"}
             for c in inputs}
    assert save_descriptions(corpus, model.id, descs)
    assert latest_model(corpus, "song").descriptions == descs
    assert not save_descriptions(corpus, 99999, descs)         # vanished row → False


def test_train_artist_clusters_buckets_by_sound(corpus):
    res = train_artist_clusters(corpus)
    assert res is not None and res["k"] == 2 and res["n_artists"] == 6
    model = latest_model(corpus, "artist")
    buckets = artist_buckets(corpus, model.id)
    grouped = {frozenset(a["artist"] for a in members) for members in buckets.values()}
    assert grouped == {
        frozenset({"CalmArtist0", "CalmArtist1", "CalmArtist2"}),
        frozenset({"LoudArtist0", "LoudArtist1", "LoudArtist2"}),
    }


def test_one_sparse_row_does_not_poison_training(corpus):
    # A track whose audio was never acquired has all-None features (the real
    # warehouse has exactly this). It must sit out, not block training.
    corpus.upsert("ghost", {"tempo_bpm": None, "rms_mean": None})
    corpus.remember_meta([{"spotify_track_id": "ghost", "track_name": "Ghost",
                           "artist_names": "Nobody"}])
    res = train_song_clusters(corpus, coords="pca")
    assert res is not None and res["n_tracks"] == 12  # ghost excluded, blobs trained
    model = latest_model(corpus, "song")
    assert "ghost" not in track_assignments(corpus, model.id)


def test_training_skips_tiny_corpora(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'tiny.db'}")
    for i in range(3):
        cache.upsert(f"t{i}", _blob_a(i))
    assert train_song_clusters(cache) is None
    assert train_artist_clusters(cache) is None
