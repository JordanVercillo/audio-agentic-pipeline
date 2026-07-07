"""
test_store.py — synthetic tests for the feature cache (APP_SPEC Epic A).

SQLite temp file, no Postgres and no real audio — exercises the cache read/write
+ the extraction-queue state machine. Runs in the existing CI job.
"""

from __future__ import annotations

import pytest

from .cache import FeatureCache

_FEATURES = {
    "tempo_bpm": 128.0, "rms_mean": 0.20, "spectral_centroid_mean": 2100.0,
    "zcr_mean": 0.05, "harmonic_ratio": 0.8,  # extra cols ride along in JSON
}


@pytest.fixture
def cache(tmp_path):
    return FeatureCache(url=f"sqlite:///{tmp_path / 'cache.db'}")


def test_upsert_and_get_roundtrip(cache):
    cache.upsert("t1", _FEATURES, spectrogram_uri="gs://x/t1.png", dsp_version="v1")
    got = cache.get(["t1", "t2"])
    assert set(got) == {"t1"}  # only cached ids returned
    assert got["t1"]["tempo_bpm"] == 128.0 and got["t1"]["harmonic_ratio"] == 0.8


def test_missing_dedups_and_excludes_cached(cache):
    cache.upsert("t1", _FEATURES)
    assert cache.missing(["t1", "t2", "t3", "t2"]) == ["t2", "t3"]


def test_enqueue_only_misses_and_is_idempotent(cache):
    cache.upsert("t1", _FEATURES)
    assert set(cache.enqueue(["t1", "t2", "t3"])) == {"t2", "t3"}  # t1 cached → skipped
    assert cache.enqueue(["t2", "t3"]) == []  # already queued → no duplicates


def test_worker_flow_claim_then_upsert_marks_done(cache):
    cache.enqueue(["t2", "t3"])
    claimed = cache.claim_next()
    assert claimed in {"t2", "t3"}
    # extraction succeeded → upsert writes the row and completes the job
    cache.upsert(claimed, _FEATURES)
    assert cache.missing([claimed]) == []
    st = cache.job_status(["t2", "t3"])
    assert st["cached"] == 1 and st["queued"] == 1  # one done, one still queued


def test_claim_next_is_fifo_and_empties(cache):
    cache.enqueue(["a", "b"])
    first, second = cache.claim_next(), cache.claim_next()
    assert {first, second} == {"a", "b"} and first == "a"  # oldest first
    assert cache.claim_next() is None  # queue drained


def test_fail_marks_failed(cache):
    cache.enqueue(["t9"])
    cache.claim_next()
    cache.fail("t9", error="yt-dlp 403")
    st = cache.job_status(["t9"])
    assert st["failed"] == 1 and st["cached"] == 0


def test_job_status_progress(cache):
    cache.upsert("done1", _FEATURES)
    cache.enqueue(["q1", "q2", "done1"])  # done1 cached → not queued
    cache.claim_next()                    # q1 → running
    st = cache.job_status(["done1", "q1", "q2"])
    assert st == {"total": 3, "cached": 1, "queued": 1, "running": 1, "failed": 0}


def test_second_instance_sees_persisted_cache(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    FeatureCache(url=url).upsert("shared", _FEATURES)
    # a fresh process/instance (e.g. a worker vs the web app) sees the same cache
    assert FeatureCache(url=url).get(["shared"])["shared"]["tempo_bpm"] == 128.0
