"""
test_store.py — synthetic tests for the feature cache (APP_SPEC Epic A).

SQLite temp file, no Postgres and no real audio — exercises the cache read/write
+ the extraction-queue state machine. Runs in the existing CI job.
"""

from __future__ import annotations

from pathlib import Path

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


def test_remember_and_get_meta(cache):
    cache.remember_meta([{"spotify_track_id": "m1", "track_name": "Hush", "artist_names": "Muse"}])
    assert cache.get_meta("m1")["track_name"] == "Hush"
    assert cache.get_meta("nope") is None


def test_similar_ranks_by_acoustic_distance(cache):
    cache.upsert("a", {"tempo_bpm": 120, "rms_mean": 0.20, "spectral_centroid_mean": 2000})
    cache.upsert("near", {"tempo_bpm": 122, "rms_mean": 0.21, "spectral_centroid_mean": 2010})
    cache.upsert("far", {"tempo_bpm": 180, "rms_mean": 0.05, "spectral_centroid_mean": 4000})
    sims = cache.similar("a", k=2)
    assert [sid for sid, _d in sims] == ["near", "far"]  # nearer first
    assert cache.similar("missing") == []


# ── extraction worker (Epic A slice 2) — synthetic audio, no YouTube ────────
def _synth_acquire(track_id, name, artist, dest_dir):
    """Injected acquire: write a synthetic WAV so the REAL DSP path runs offline."""
    import soundfile as sf

    from ..dsp.audio_loader import generate_test_signal
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=5.0)
    path = Path(dest_dir)
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"{track_id}.wav"
    sf.write(out, sig.waveform, sig.sr)
    return out


def test_extract_one_runs_real_dsp_on_synthetic_audio(cache, tmp_path):
    from .extractor import extract_one
    cache.remember_meta([{"spotify_track_id": "s1", "track_name": "Test", "artist_names": "Synth"}])
    cache.enqueue(["s1"])
    tid = cache.claim_next()
    ok = extract_one(cache, tid, audio_dir=tmp_path / "audio",
                     spectrogram_dir=tmp_path / "spec", acquire=_synth_acquire)
    assert ok is True
    feats = cache.get(["s1"])["s1"]
    assert "tempo_bpm" in feats and "rms_mean" in feats  # real 82-col dict from DSP
    assert (tmp_path / "spec" / "s1.png").exists()       # mel-spectrogram rendered
    assert cache.missing(["s1"]) == []                   # cached → job done
    assert not (tmp_path / "audio" / "s1.wav").exists()  # audio deleted (D-15)


def test_extract_one_no_metadata_fails(cache, tmp_path):
    from .extractor import extract_one
    cache.enqueue(["s2"])  # queued but no remember_meta → no search query
    cache.claim_next()
    ok = extract_one(cache, "s2", audio_dir=tmp_path / "a",
                     spectrogram_dir=tmp_path / "s", acquire=_synth_acquire)
    assert ok is False and cache.job_status(["s2"])["failed"] == 1


def test_extract_one_acquire_failure_fails(cache, tmp_path):
    from .extractor import extract_one
    cache.remember_meta([{"spotify_track_id": "s3", "track_name": "X", "artist_names": "Y"}])
    cache.enqueue(["s3"])
    cache.claim_next()
    ok = extract_one(cache, "s3", audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
                     acquire=lambda *a: None)  # acquisition returns nothing
    assert ok is False and cache.job_status(["s3"])["failed"] == 1


def test_drain_processes_the_queue(cache, tmp_path):
    from .extractor import drain
    cache.remember_meta([{"spotify_track_id": f"d{i}", "track_name": f"T{i}", "artist_names": "A"}
                         for i in range(2)])
    cache.enqueue(["d0", "d1"])
    res = drain(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
                acquire=_synth_acquire)
    assert res == {"done": 2, "failed": 0}
    assert cache.missing(["d0", "d1"]) == []
