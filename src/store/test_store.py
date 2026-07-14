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


def test_upsert_preserves_display_columns_when_not_supplied(cache):
    # a features-only re-write (re-running seed_cache after the F-v2 backfills)
    # must NOT null the backfilled loudness curve / meter / beat grid
    cache.upsert("t1", _FEATURES, spectrogram_uri="path/x.png",
                 loudness_curve=[-30.0, -10.0], time_signature=4, beat_times=[0.5, 1.0])
    cache.upsert("t1", {**_FEATURES, "tempo_bpm": 99.0})  # like seed_cache: no display kwargs
    assert cache.get(["t1"])["t1"]["tempo_bpm"] == 99.0   # features DID update
    assert cache.loudness_curve("t1") == [-30.0, -10.0]   # display columns PRESERVED
    assert cache.all_time_signatures()["t1"] == 4
    assert cache.beat_times("t1") == [0.5, 1.0]


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


def test_failed_job_dead_letters_after_max_attempts(cache):
    # A permanently-unfetchable track must NOT hot-loop forever: attempts are
    # preserved across retries and the job dead-letters at the cap.
    from .cache import MAX_ATTEMPTS
    cache.enqueue(["x"])
    for i in range(1, MAX_ATTEMPTS + 1):
        assert cache.claim_next() == "x"          # attempts climbs 1..MAX (preserved)
        cache.fail("x", "yt-dlp 403")
        requeued = cache.enqueue(["x"])
        assert requeued == (["x"] if i < MAX_ATTEMPTS else [])  # retriable until the cap
    assert cache.claim_next() is None             # dead-lettered → never re-queued
    assert cache.job_status(["x"])["failed"] == 1


def test_enqueue_preserves_attempts_across_retry(cache):
    cache.enqueue(["y"])
    cache.claim_next()                            # attempts → 1
    cache.fail("y")
    cache.enqueue(["y"])                          # retry must NOT reset to 0
    cache.claim_next()                            # attempts → 2 (not 1)
    cache.fail("y")
    cache.enqueue(["y"])                          # attempts=2 < 3 → still retriable
    assert cache.claim_next() == "y"              # attempts → 3


def test_job_status_progress(cache):
    cache.upsert("done1", _FEATURES)
    cache.enqueue(["q1", "q2", "done1"])  # done1 cached → not queued
    cache.claim_next()                    # q1 → running
    st = cache.job_status(["done1", "q1", "q2"])
    assert st == {"total": 3, "cached": 1, "queued": 1, "running": 1, "failed": 0}


def test_sqlite_wal_enabled_for_file_db(tmp_path):
    # webapp + worker share the file across processes — WAL must be on (D-12).
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'w.db'}")
    with c.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert str(mode).lower() == "wal"


def test_second_instance_sees_persisted_cache(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    FeatureCache(url=url).upsert("shared", _FEATURES)
    # a fresh process/instance (e.g. a worker vs the web app) sees the same cache
    assert FeatureCache(url=url).get(["shared"])["shared"]["tempo_bpm"] == 128.0


def test_remember_and_get_meta(cache):
    cache.remember_meta([{"spotify_track_id": "m1", "track_name": "Hush", "artist_names": "Muse"}])
    assert cache.get_meta("m1")["track_name"] == "Hush"
    assert cache.get_meta("nope") is None


def test_remember_meta_popularity_preserve_if_absent(cache):
    # popularity rides along when present (fetched context — journal #20)…
    cache.remember_meta([{"spotify_track_id": "p1", "track_name": "Song",
                          "artist_names": "Band", "popularity": 61}])
    assert cache.get_meta("p1")["popularity"] == 61
    # …and a later item WITHOUT it must not NULL what an earlier fetch stored
    # (the field is deprecated upstream and can vanish from responses any day).
    cache.remember_meta([{"spotify_track_id": "p1", "track_name": "Song (Remaster)"}])
    m = cache.get_meta("p1")
    assert m["popularity"] == 61 and m["track_name"] == "Song (Remaster)"
    assert m["artist_names"] == "Band"                 # omitted field preserved too
    cache.remember_meta([{"spotify_track_id": "p1", "popularity": 70}])
    assert cache.get_meta("p1")["popularity"] == 70    # last sight wins
    assert cache.all_popularity() == {"p1": 70}        # corpus baseline getter


def test_loudness_curve_upsert_and_targeted_update(cache):
    # upsert carries the curve; get it back
    cache.upsert("t1", _FEATURES, loudness_curve=[-30.0, -12.0, -6.0])
    assert cache.loudness_curve("t1") == [-30.0, -12.0, -6.0]
    assert cache.loudness_curve("missing") is None
    # set_loudness_curve updates ONLY the column — features stay intact
    assert cache.set_loudness_curve("t1", [-40.0, -20.0]) is True
    assert cache.loudness_curve("t1") == [-40.0, -20.0]
    assert cache.get(["t1"])["t1"]["tempo_bpm"] == 128.0  # features untouched
    # no row → no-op, reported
    assert cache.set_loudness_curve("ghost", [-1.0]) is False


def test_time_signature_upsert_targeted_update_and_map(cache):
    cache.upsert("t1", _FEATURES, time_signature=3)
    cache.upsert("t2", _FEATURES)                       # no meter → excluded from the map
    assert cache.all_time_signatures() == {"t1": 3}
    assert cache.set_time_signature("t1", 5) is True
    assert cache.all_time_signatures()["t1"] == 5
    assert cache.set_time_signature("ghost", 4) is False  # no row → no-op
    cache.upsert("t3", _FEATURES, time_signature=0)      # 0 = unknown → stored NULL
    assert "t3" not in cache.all_time_signatures()


def test_sections_upsert_preserved_and_targeted_update(cache):
    secs = [{"start": 0.0, "end": 30.0, "label": 0, "tempo_bpm": 120.0,
             "loudness_db": -12.0, "key": 9, "mode": "minor"}]
    cache.upsert("t1", _FEATURES, sections=secs)
    assert cache.sections("t1") == secs
    cache.upsert("t1", _FEATURES)                      # features-only re-write…
    assert cache.sections("t1") == secs                # …preserves sections (like F-v2 cols)
    assert cache.set_sections("t1", secs + secs) is True
    assert len(cache.sections("t1")) == 2
    assert cache.sections("missing") is None
    assert cache.set_sections("ghost", secs) is False  # no row → no-op


def test_beat_times_upsert_targeted_update_and_get(cache):
    cache.upsert("t1", _FEATURES, beat_times=[0.5, 1.0, 1.5])
    assert cache.beat_times("t1") == [0.5, 1.0, 1.5]
    assert cache.beat_times("missing") is None
    assert cache.set_beat_times("t1", [0.5, 1.0]) is True   # targeted update
    assert cache.beat_times("t1") == [0.5, 1.0]
    assert cache.get(["t1"])["t1"]["tempo_bpm"] == 128.0    # features untouched
    assert cache.set_beat_times("ghost", [0.1]) is False    # no row → no-op


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
    assert "loudness_curve" not in feats                 # curve rides separately, not in features
    curve = cache.loudness_curve("s1")                   # F-v2: real curve persisted
    assert isinstance(curve, list) and len(curve) >= 2 and all(v <= 0 for v in curve)
    assert 2 <= cache.all_time_signatures()["s1"] <= 7   # F-v2b: meter estimated + stored
    assert isinstance(cache.beat_times("s1"), list)      # F-v2c: beat grid persisted
    assert (tmp_path / "spec" / "s1.png").exists()       # mel-spectrogram rendered
    assert cache.missing(["s1"]) == []                   # cached → job done
    assert not (tmp_path / "audio" / "s1.wav").exists()  # audio deleted (D-15)


def test_extract_one_rejects_path_shaped_ids(cache, tmp_path):
    # The id becomes a filename — a path-shaped id must fail BEFORE acquisition.
    from .extractor import extract_one

    def _must_not_run(*a):
        raise AssertionError("acquire must not be called for an invalid id")

    for bad in ("../../etc/passwd", "a/b", "x" * 100, ""):
        ok = extract_one(cache, bad, audio_dir=tmp_path / "a",
                         spectrogram_dir=tmp_path / "s", acquire=_must_not_run)
        assert ok is False


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


def test_drain_on_progress_fires_per_job(cache, tmp_path):
    # A long queue must keep beating the caller's heartbeat — even for failures.
    from .extractor import drain
    cache.enqueue(["p0", "p1"])  # no metadata → both fail fast, no DSP needed
    beats = []
    drain(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
          acquire=lambda *a: None, on_progress=lambda: beats.append(1))
    assert len(beats) == 2


# ── worker liveness (heartbeat + orphan re-queue) ────────────────────────────
def test_beat_upserts_a_single_row(cache):
    cache.beat("extraction-worker", pid=111, interval_seconds=30)
    first = cache.heartbeat("extraction-worker")
    cache.beat("extraction-worker", pid=222, interval_seconds=60)
    second = cache.heartbeat("extraction-worker")
    assert first is not None and second is not None
    assert second["pid"] == 222 and second["interval_seconds"] == 60
    assert second["beat_at"] >= first["beat_at"]  # moved forward, same row
    assert cache.heartbeat("never-ran") is None


def test_requeue_stale_running_reclaims_orphans(cache):
    cache.enqueue(["stuck"])
    assert cache.claim_next() == "stuck"  # → running (then the "worker" dies)
    with cache.engine.begin() as conn:  # backdate: simulate a long-dead claim
        conn.exec_driver_sql(
            "UPDATE extraction_jobs SET updated_at = '2020-01-01 00:00:00.000000'")
    assert cache.requeue_stale_running(older_than_seconds=900) == ["stuck"]
    assert cache.job_status(["stuck"])["queued"] == 1
    assert cache.claim_next() == "stuck"  # claimable again


def test_requeue_leaves_fresh_running_alone(cache):
    cache.enqueue(["live"])
    cache.claim_next()
    assert cache.requeue_stale_running(older_than_seconds=900) == []
    assert cache.job_status(["live"])["running"] == 1


def test_seed_skips_metadata_only_ghost(cache, tmp_path, monkeypatch):
    """A never-downloaded warehouse row must seed META only — seeded empty
    features read 'analyzed, forever empty' and the queue can't repair them
    (journal #13's ghost, observed live as the Hummer row)."""
    import importlib.util
    import sys as _sys

    import pandas as pd

    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_cache.py"
    spec = importlib.util.spec_from_file_location("seed_cache", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    modeled = tmp_path / "modeled"
    modeled.mkdir()
    pd.DataFrame([
        {"spotify_track_id": "real", "time_range": "short_term", "rank": 1,
         "track_name": "Real", "artist_names": "A", "tempo_bpm": 120.0,
         "rms_mean": 0.2},
        {"spotify_track_id": "ghost", "time_range": "short_term", "rank": 2,
         "track_name": "Ghost", "artist_names": "B", "tempo_bpm": None,
         "rms_mean": None},  # metadata-only: the DSP never ran
    ]).to_parquet(modeled / "fact_listening_features.parquet", index=False)

    monkeypatch.setattr(mod, "_MODELED", modeled)
    monkeypatch.setattr(mod, "FeatureCache", lambda: cache)
    monkeypatch.setattr(_sys, "argv", ["seed_cache.py"])
    assert mod.main() == 0

    assert set(cache.get(["real", "ghost"])) == {"real"}   # ghost NOT seeded
    assert cache.get_meta("ghost")["track_name"] == "Ghost"  # meta kept for later
    assert cache.missing(["ghost"]) == ["ghost"]           # queue CAN repair it


def test_another_worker_alive_decision(cache):
    from datetime import datetime, timedelta, timezone

    from .extractor import another_worker_alive
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fresh = {"pid": 111, "interval_seconds": 30, "beat_at": now - timedelta(seconds=60)}
    stale = {"pid": 111, "interval_seconds": 30, "beat_at": now - timedelta(seconds=3600)}
    assert another_worker_alive(fresh, my_pid=222, now=now) is True    # other pid, fresh → refuse
    assert another_worker_alive(fresh, my_pid=111, now=now) is False   # our own beat → fine
    assert another_worker_alive(stale, my_pid=222, now=now) is False   # dead worker → start
    assert another_worker_alive(None, my_pid=222, now=now) is False    # never ran → start
    future = {"pid": 111, "interval_seconds": 30, "beat_at": now + timedelta(seconds=60)}
    assert another_worker_alive(future, my_pid=222, now=now) is True   # clock skew → be safe
    # end-to-end through the cache: a live beat from another pid blocks a start
    cache.beat("extraction-worker", pid=111, interval_seconds=30)
    assert another_worker_alive(cache.heartbeat("extraction-worker"), my_pid=222) is True


def test_app_verify_worker_flags():
    # Import the skill script's pure flag logic (same pattern as check_marts).
    import importlib.util
    path = (Path(__file__).resolve().parents[2]
            / ".claude" / "skills" / "app-verify" / "verify_app.py")
    spec = importlib.util.spec_from_file_location("verify_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    flags = mod.evaluate_worker_flags

    assert flags(None, None, None)["WORKER_DOWN"] is True          # never beat
    assert flags(10.0, 30, None) == {"WORKER_DOWN": False, "QUEUE_STUCK": False}
    assert flags(10_000.0, 30, None)["WORKER_DOWN"] is True        # stale beat
    assert flags(200.0, 30, None)["WORKER_DOWN"] is False          # < 300s floor
    assert flags(10.0, 30, 1200.0)["QUEUE_STUCK"] is True          # old pending job
    assert flags(10.0, 30, 60.0)["QUEUE_STUCK"] is False           # fresh queue


# ── O1 dedup guards (Epic O / D-28) ──────────────────────────────────────────
def test_enqueue_guard_skips_cached_twin(cache):
    # 'orig' is cached; 'orig2' is the SAME recording arriving as a fresh miss
    # (same name+artist, 100 ms apart) → it must NOT be re-downloaded.
    cache.upsert("orig", _FEATURES)
    cache.remember_meta([
        {"spotify_track_id": "orig", "track_name": "Hysteria", "artist_names": "Muse", "duration_ms": 200000},
        {"spotify_track_id": "orig2", "track_name": "Hysteria - Remastered", "artist_names": "Muse", "duration_ms": 200100}])
    assert cache.enqueue(["orig2"]) == []                    # twin already cached → skipped
    assert cache.duplicate_flags() == {"orig2": "orig"}      # flagged as a dupe of the canonical
    assert cache.get(["orig2"]) == {}                        # never downloaded (no features)
    assert cache.enqueue(["orig2"]) == []                    # idempotent
    # the bridge key is untouched on both rows — dedup mints/merges no id
    assert cache.get_meta("orig2")["spotify_track_id"] == "orig2"


def test_enqueue_guard_does_not_flag_distinct_track(cache):
    cache.upsert("orig", _FEATURES)
    cache.remember_meta([
        {"spotify_track_id": "orig", "track_name": "Hysteria", "artist_names": "Muse", "duration_ms": 200000},
        {"spotify_track_id": "other", "track_name": "Uprising", "artist_names": "Muse", "duration_ms": 300000}])
    assert cache.enqueue(["other"]) == ["other"]             # genuinely new → queued normally
    assert cache.duplicate_flags() == {}


def test_refresh_duplicate_flags_idempotent_and_annotation_only(cache):
    # 3 cached tracks so the cosine tiebreak isn't degenerate; a/b are the same
    # recording (near-identical features), c is distinct (anchors the z-scoring).
    cache.upsert("a", {"tempo_bpm": 128.0, "rms_mean": 0.20, "spectral_centroid_mean": 2100.0})
    cache.upsert("b", {"tempo_bpm": 129.0, "rms_mean": 0.21, "spectral_centroid_mean": 2110.0})
    cache.upsert("c", {"tempo_bpm": 80.0, "rms_mean": 0.05, "spectral_centroid_mean": 900.0})
    cache.remember_meta([
        {"spotify_track_id": "a", "track_name": "Time", "artist_names": "Muse", "duration_ms": 240000},
        {"spotify_track_id": "b", "track_name": "Time - 2019 Remaster", "artist_names": "Muse", "duration_ms": 240200},
        {"spotify_track_id": "c", "track_name": "Sunburn", "artist_names": "Muse", "duration_ms": 200000}])
    r1 = cache.refresh_duplicate_flags()
    assert r1["n_duplicates"] == 1                           # a/b are one recording, c stands alone
    assert cache.refresh_duplicate_flags()["n_updated"] == 0  # idempotent — recompute writes nothing
    assert set(cache.get(["a", "b", "c"])) == {"a", "b", "c"}  # features untouched (annotation-only)
    flags = cache.duplicate_flags()
    assert len(flags) == 1 and set(flags) <= {"a", "b"} and set(flags.values()) <= {"a", "b"}
