"""
test_store.py — synthetic tests for the feature cache (APP_SPEC Epic A).

SQLite temp file, no Postgres and no real audio — exercises the cache read/write
+ the extraction-queue state machine. Runs in the existing CI job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .cache import MAX_ATTEMPTS, FeatureCache

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
    # neighbours must be SOURCE-VALIDATED to be offered (owner call 2026-07-23)
    for t in ("a", "near", "far"):
        cache.remember_provenance(spotify_track_id=t, youtube_url=f"https://y/{t}")
    sims = cache.similar("a", k=2)
    assert [sid for sid, _d in sims] == ["near", "far"]  # nearer first
    assert cache.similar("missing") == []


# ── extraction worker (Epic A slice 2) — synthetic audio, no YouTube ────────
def _synth_acquire(track_id, name, artist, dest_dir, duration_s=None):
    """Injected acquire: write a synthetic WAV so the REAL DSP path runs offline.
    Returns (path, match) per the O2 AcquireFn contract."""
    import soundfile as sf

    from ..dsp.audio_loader import generate_test_signal
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=5.0)
    path = Path(dest_dir)
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"{track_id}.wav"
    sf.write(out, sig.waveform, sig.sr)
    return out, {"url": "synthetic", "title": "synthetic", "score": 35,
                 "confidence": 1.0, "duration_delta_s": 0.0}


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


def _synth_acquire_full(track_id, name, artist, dest_dir, duration_s=None):
    """Like _synth_acquire but returns the FULL Epic-Q match record (D-51)."""
    path, _ = _synth_acquire(track_id, name, artist, dest_dir, duration_s)
    return path, {"url": "https://youtu.be/abc123", "title": "Test — Official Audio",
                  "score": 35, "confidence": 0.86, "duration_delta_s": 1.4,
                  "youtube_video_id": "abc123", "youtube_duration_s": 214.0,
                  "channel": "TestVEVO", "candidate_count": 5,
                  "query": "Synth Test official audio", "matcher_version": "heuristic-v1"}


def test_extract_one_records_provenance(cache, tmp_path):
    # Q1/D-51: a successful extraction appends ONE provenance event carrying
    # everything the matcher already knew (zero new fetches).
    from .extractor import DSP_VERSION, extract_one
    cache.remember_meta([{"spotify_track_id": "p1", "track_name": "Test",
                          "artist_names": "Synth"}])
    cache.enqueue(["p1"])
    tid = cache.claim_next()
    assert extract_one(cache, tid, audio_dir=tmp_path / "a",
                       spectrogram_dir=tmp_path / "s", acquire=_synth_acquire_full)
    rows = cache.all_provenance()
    assert len(rows) == 1
    r = rows[0]
    assert r["spotify_track_id"] == "p1"
    assert r["youtube_url"] == "https://youtu.be/abc123" and r["youtube_video_id"] == "abc123"
    assert r["youtube_title"] == "Test — Official Audio" and r["channel"] == "TestVEVO"
    assert r["match_confidence"] == 0.86 and r["match_score"] == 35
    assert r["duration_delta_s"] == 1.4 and r["candidate_count"] == 5
    assert r["matcher_version"] == "heuristic-v1" and r["dsp_version"] == DSP_VERSION
    assert r["audio_format"] == "mp3" and r["audio_bitrate_kbps"] == 192


def test_provenance_is_append_only_and_best_effort(cache):
    # Append per event (soft ref, not unique); a re-extraction adds a row.
    a = cache.remember_provenance(spotify_track_id="x", youtube_url="u1",
                                  match_confidence=0.5)
    b = cache.remember_provenance(spotify_track_id="x", youtube_url="u2",
                                  match_confidence=0.9, bogus="dropped")
    assert a > 0 and b > a
    rows = cache.all_provenance()
    assert [r["youtube_url"] for r in rows] == ["u2", "u1"]   # newest first, both kept
    # unknown kwarg silently dropped, never raises
    assert cache.remember_provenance(spotify_track_id="y") > 0


def test_similar_excludes_twin_candidates(cache):
    # O3b: a twin must not be its canonical's "similar song" (it IS the song).
    for tid, tempo in (("c1", 120.0), ("t1", 120.5), ("d1", 125.0)):
        cache.upsert(tid, {"tempo_bpm": tempo, "rms_mean": 0.3,
                           "zcr_mean": 0.05, "spectral_centroid_mean": 2000.0})
    cache.remember_meta([{"spotify_track_id": t, "track_name": t, "artist_names": "A"}
                         for t in ("c1", "t1", "d1")])
    # similar() only offers SOURCE-VALIDATED neighbours (owner call 2026-07-23)
    for t in ("c1", "t1", "d1"):
        cache.remember_provenance(spotify_track_id=t, youtube_url=f"https://y/{t}")
    with cache._Session() as s:
        from .models import TrackMeta
        s.get(TrackMeta, "t1").duplicate_of = "c1"
        s.commit()
    ids = [tid for tid, _ in cache.similar("c1", k=5)]
    assert "t1" not in ids and "d1" in ids                 # twin out, real neighbor in
    # …but a twin can still be the QUERY (its /song page keeps working)
    assert cache.similar("t1", k=5)


def test_quarantine_tracks_removes_analysis_keeps_bridge_key(cache):
    # DQ1: a not-confident track's WRONG analysis is deleted (stops polluting
    # marts) and its job dead-lettered (worker won't re-grab), but the bridge
    # key survives and a D-56 repair can re-analyze it.
    from .models import TrackCluster, TrackPerceptual
    cache.upsert("wrong", {"tempo_bpm": 120.0, "rms_mean": 0.3,
                           "spectral_centroid_mean": 2000.0})
    cache.remember_meta([{"spotify_track_id": "wrong", "track_name": "Real Song",
                          "artist_names": "Real Artist"}])
    cache.remember_provenance(spotify_track_id="wrong", youtube_url="u",
                              youtube_title="Some Other Song")
    with cache._Session() as s:
        s.add(TrackPerceptual(spotify_track_id="wrong", features={"tempo": 120.0},
                              version="perceptual-v1"))
        s.add(TrackCluster(spotify_track_id="wrong", model_id=1, cluster_id=0))
        s.commit()

    n = cache.quarantine_tracks({"wrong": "wrong-song swap — needs manual source"})
    assert n == 1
    assert cache.get(["wrong"]) == {}                        # features gone
    assert cache.provenance_for("wrong") is None             # provenance gone
    assert cache.get_perceptual(["wrong"]) == {}             # perceptual gone
    assert cache.get_meta("wrong")["track_name"] == "Real Song"  # bridge key KEPT
    # dead-lettered → enqueue refuses to re-queue it (worker can't re-grab)
    assert cache.enqueue(["wrong"]) == []
    assert cache.job_status(["wrong"])["failed"] == 1
    # …but a D-56 repair path (direct upsert) still re-analyzes it
    cache.upsert("wrong", {"tempo_bpm": 128.0, "rms_mean": 0.4})
    assert cache.get(["wrong"])["wrong"]["tempo_bpm"] == 128.0
    assert cache.quarantine_tracks({}) == 0                   # empty is a no-op


def test_provenance_for_returns_current_event(cache):
    # Q2/D-51: /song reads the LATEST event for a track.
    assert cache.provenance_for("nope") is None            # ∅ until extracted
    cache.remember_provenance(spotify_track_id="t", youtube_url="old", match_confidence=0.3)
    cache.remember_provenance(spotify_track_id="t", youtube_url="new", match_confidence=0.9)
    cur = cache.provenance_for("t")
    assert cur["youtube_url"] == "new" and cur["match_confidence"] == 0.9


def test_library_rows_carry_provenance_glyph(cache):
    # Q2/D-51: ✓ (conf≥0.5) / ~ (conf<0.5, the S2 remix band) / ∅ (no event).
    cache.remember_meta([{"spotify_track_id": t, "track_name": t, "artist_names": "A"}
                         for t in ("good", "low", "none")])
    cache.remember_provenance(spotify_track_id="good", match_confidence=0.86)
    cache.remember_provenance(spotify_track_id="low", match_confidence=0.2)
    by_id = {r["id"]: r for r in cache.library_rows()}
    assert by_id["good"]["provenance"] == "ok"
    assert by_id["low"]["provenance"] == "low"
    assert by_id["none"]["provenance"] is None


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
                     acquire=lambda *a: (None, None))  # acquisition returns nothing
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
          acquire=lambda *a: (None, None), on_progress=lambda: beats.append(1))
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
    assert flags(10.0, 30, 0) == {"WORKER_DOWN": False, "QUEUE_STUCK": False}
    assert flags(10_000.0, 30, 0)["WORKER_DOWN"] is True           # stale beat
    assert flags(200.0, 30, 0)["WORKER_DOWN"] is False             # < 300s floor
    # QUEUE_STUCK = pending work + NO recent progress (session-36 re-semantics:
    # a deep-but-draining import backlog must NOT alarm)
    assert flags(10.0, 30, 48, 45.0)["QUEUE_STUCK"] is False       # deep + draining
    assert flags(10.0, 30, 48, 1200.0)["QUEUE_STUCK"] is True      # pending, no progress
    assert flags(10.0, 30, 48, None)["QUEUE_STUCK"] is True        # pending, never progressed
    assert flags(10.0, 30, 0, 99999.0)["QUEUE_STUCK"] is False     # empty queue never stuck


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


def test_find_cached_twin_matches_cached_recording(cache):
    # the signal the extract-time (both-new race) guard fires on: 'second' was
    # queued when nothing was cached; once 'first' analyzes, its twin is found.
    cache.upsert("first", _FEATURES)
    cache.remember_meta([
        {"spotify_track_id": "first", "track_name": "Starlight", "artist_names": "Muse", "duration_ms": 240000},
        {"spotify_track_id": "second", "track_name": "Starlight - Remastered 2019", "artist_names": "Muse", "duration_ms": 240300}])
    assert cache.find_cached_twin("second") == "first"       # → extract_one reuses first, skips DSP
    assert cache.find_cached_twin("first") is None           # canonical has no cached twin
    assert cache.find_cached_twin("unknown") is None         # unknown id → None, never raises


def test_find_cached_twin_refuses_a_different_version(cache):
    """O4: a live take is DIFFERENT AUDIO, so the acquisition guard must let it
    download. Pre-O4 this returned the studio original and the live version
    silently inherited its features — the false-merge direction, which also
    writes a terminal `done` job."""
    cache.upsert("studio", _FEATURES)
    cache.remember_meta([
        {"spotify_track_id": "studio", "track_name": "Starlight", "artist_names": "Muse", "duration_ms": 240000},
        {"spotify_track_id": "onstage", "track_name": "Starlight - Live", "artist_names": "Muse", "duration_ms": 240300}])
    assert cache.find_cached_twin("onstage") is None
    assert cache.enqueue(["onstage"]) == ["onstage"]         # it gets its own audio


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


def test_clearing_a_twin_flag_does_not_strand_the_track(cache):
    """A twin resolved at enqueue time gets job=done with a "deduped:" note. If a
    later rule change CLEARS that flag, the track becomes a distinct un-analyzed
    song — and `done` is terminal, so `enqueue` would never queue it again: a
    permanent ghost, counted in the corpus and fillable by nothing. The refresh
    must re-open the job it authored."""
    cache.upsert("canon", _FEATURES)
    cache.remember_meta([
        {"spotify_track_id": "canon", "track_name": "Bliss", "artist_names": "Muse", "duration_ms": 240000},
        {"spotify_track_id": "twin", "track_name": "Bliss - Deluxe", "artist_names": "Muse", "duration_ms": 240100}])
    assert cache.enqueue(["twin"]) == []                      # guarded away, job closed
    assert cache.duplicate_flags() == {"twin": "canon"}
    assert cache.job_states()["twin"][0] == "done"

    # the rule changes its mind: the twin is really a different recording
    cache.remember_meta([{"spotify_track_id": "twin", "track_name": "Bliss - Live",
                          "artist_names": "Muse", "duration_ms": 240100}])
    r = cache.refresh_duplicate_flags()
    assert cache.duplicate_flags() == {}                      # flag cleared
    assert r["n_unstranded"] == 1 and r["unstranded"] == ["twin"]
    assert cache.job_states()["twin"][0] == "queued"          # re-openable, not a ghost
    assert cache.enqueue(["twin"]) == [] or cache.job_states()["twin"][0] == "queued"


def test_queue_count_is_the_queue_not_the_page(cache):
    """`queue_rows` is display-capped, so /queue derived its count AND its ETA
    from the length of a truncated list. Invisible while imports were capped at
    100; materially wrong now that a whole playlist lands at once — a 1000-track
    import would have reported "200 tracks · 167 min" instead of a day."""
    ids = [f"q{i:04d}" for i in range(250)]
    cache.remember_meta([{"spotify_track_id": t, "track_name": t,
                          "artist_names": "A"} for t in ids])
    cache.enqueue(ids)
    assert cache.queue_count() == 250
    assert len(cache.queue_rows()) < 250        # the display cap still applies
    cache.claim_next()                          # running still counts as queued work
    assert cache.queue_count() == 250


def test_playlist_membership_merges_by_default(cache):
    """Membership is what lets /playlists say "N of M analyzed" AND what tells
    the next import where to resume. A capped import reads only a PREFIX of a
    large playlist, so merging is the default — replacing would make each click
    forget what the last one learned and the resume offset would never advance."""
    cache.remember_playlist_tracks("pl1", ["a", "b", "c", "b"])   # dupes collapse
    assert sorted(cache.playlist_track_ids()["pl1"]) == ["a", "b", "c"]
    cache.remember_playlist_tracks("pl1", ["d", "e"])             # the next page
    assert sorted(cache.playlist_track_ids()["pl1"]) == ["a", "b", "c", "d", "e"]
    assert cache.remember_playlist_tracks("pl2", []) == 0         # nothing to record
    assert "pl2" not in cache.playlist_track_ids()


def test_a_complete_walk_replaces_so_removals_take_effect(cache):
    """Only a walk that reached the END knows the full membership, and only then
    may a track removed upstream actually leave. Merging forever would let a
    deleted track haunt the coverage count."""
    cache.remember_playlist_tracks("pl1", ["a", "b", "c"])
    cache.remember_playlist_tracks("pl1", ["a", "d"], replace=True)
    assert sorted(cache.playlist_track_ids()["pl1"]) == ["a", "d"]


def test_analyzed_ids_matches_the_full_feature_read(cache):
    """The 90x cheaper path must be the SAME answer — it replaced
    `set(all_features())` under excluded_from_aggregates(), which gates every
    aggregate in the app."""
    for t in ("a", "b", "c"):
        cache.upsert(t, _FEATURES)
    assert cache.analyzed_ids() == set(cache.all_features()) == {"a", "b", "c"}


def test_unstranding_never_reopens_a_real_failure(cache):
    """Only jobs the dedup path authored may be re-opened. A genuine failure
    keeps its error and its attempt count — otherwise a dead-lettered track
    would hot-loop again (the journal-#22 availability bug)."""
    cache.remember_meta([{"spotify_track_id": "bad", "track_name": "Nope",
                          "artist_names": "Muse", "duration_ms": 100000}])
    cache.enqueue(["bad"])
    cache.fail("bad", "no usable source — title mismatch")
    before = cache.job_states()["bad"]
    cache.refresh_duplicate_flags()
    assert cache.job_states()["bad"] == before


# ── artist metadata (P3.1 / D-36) ────────────────────────────────────────────
def test_remember_artists_preserve_if_absent(cache):
    cache.remember_artists([{"artist_id": "ar1", "artist_name": "Muse",
                             "genres": "rock, prog", "followers": 100,
                             "popularity": 78, "image_url": "http://img/1"}])
    # a later sparse fetch (genres emptied upstream, fields absent) must not
    # NULL the stored copy — the D-36 system-of-record posture
    cache.remember_artists([{"artist_id": "ar1", "artist_name": "Muse", "genres": ""}])
    got = cache.all_artist_meta()["ar1"]
    assert got["genres"] == "rock, prog"                # "" never overwrites
    assert got["followers"] == 100 and got["popularity"] == 78
    assert got["image_url"] == "http://img/1"
    # last-sight-wins when a value IS present
    cache.remember_artists([{"artist_id": "ar1", "popularity": 80}])
    assert cache.all_artist_meta()["ar1"]["popularity"] == 80
    # id-less items are skipped, absent-safe
    cache.remember_artists([{"artist_name": "Ghost"}])
    assert set(cache.all_artist_meta()) == {"ar1"}


def test_match_confidence_recorded_and_preserved(cache):
    # O2 acceptance: confidence recorded per extraction; a features-only
    # re-write (no match kwarg) preserves it — same posture as the display cols.
    cache.upsert("m1", _FEATURES, match_confidence=0.85)
    with cache._Session() as s:
        from .models import TrackFeatures
        assert s.get(TrackFeatures, "m1").match_confidence == 0.85
    cache.upsert("m1", {**_FEATURES, "tempo_bpm": 99.0})  # seed_cache-style rewrite
    with cache._Session() as s:
        from .models import TrackFeatures
        assert s.get(TrackFeatures, "m1").match_confidence == 0.85  # not NULLed


def test_extract_one_records_match_confidence(cache, tmp_path):
    from .extractor import extract_one
    cache.remember_meta([{"spotify_track_id": "mc1", "track_name": "T",
                          "artist_names": "A", "duration_ms": 5000}])
    cache.enqueue(["mc1"])
    seen: dict = {}

    def acquire(track_id, name, artist, dest_dir, duration_s=None):
        seen["duration_s"] = duration_s          # meta's duration_ms threaded in
        return _synth_acquire(track_id, name, artist, dest_dir)

    tid = cache.claim_next()
    assert extract_one(cache, tid, audio_dir=tmp_path / "a",
                       spectrogram_dir=tmp_path / "s", acquire=acquire)
    assert seen["duration_s"] == 5.0
    with cache._Session() as s:
        from .models import TrackFeatures
        assert s.get(TrackFeatures, "mc1").match_confidence == 1.0


def test_ungraded_chat_turns_excludes_labeled(cache):
    # D-47: the review sampler's pool = ChatLog rows without a ChatLabel.
    a = cache.log_chat_turn(chat_session_id="s", turn_index=0, mode="adhoc",
                            source="llm", parsed_answer="a", latency_ms=40)
    b = cache.log_chat_turn(chat_session_id="s", turn_index=1, mode="story",
                            source="fallback", parsed_answer="b", latency_ms=5)
    assert {r["id"] for r in cache.ungraded_chat_turns()} == {a, b}
    cache.write_chat_label(log_id=a, rubric_version="rubric-v1", accuracy=2,
                           citation_fidelity=2, invention=0, verdict="good", grader="jordan")
    assert {r["id"] for r in cache.ungraded_chat_turns()} == {b}   # a now graded
    labels = cache.all_chat_labels()
    assert len(labels) == 1 and labels[0]["log_id"] == a and labels[0]["verdict"] == "good"


def test_review_pool_excludes_synthetic_llm_turns(cache):
    # An llm row with no positive latency is impossible for a real Ollama call —
    # deploy-validation traffic (the live 'vibe?' 0 ms bursts). It must never
    # reach the review sampler or the K5 counter, but stays in the DB.
    good = cache.log_chat_turn(chat_session_id="s", turn_index=0, mode="adhoc",
                               source="llm", parsed_answer="real", latency_ms=1200)
    zero = cache.log_chat_turn(chat_session_id="s", turn_index=1, mode="adhoc",
                               source="llm", parsed_answer="vibe?", latency_ms=0)
    none = cache.log_chat_turn(chat_session_id="s", turn_index=2, mode="story",
                               source="llm", parsed_answer="untimed")  # latency None
    fb = cache.log_chat_turn(chat_session_id="s", turn_index=3, mode="adhoc",
                             source="fallback", parsed_answer="fb", latency_ms=0)
    pool = {r["id"] for r in cache.ungraded_chat_turns()}
    assert good in pool and fb in pool          # real llm + instant fallback kept
    assert zero not in pool and none not in pool  # synthetic llm excluded
    assert {r["id"] for r in cache.recent_chat_turns()} == pool


def test_chat_log_roundtrip_and_best_effort(cache):
    # D-47: log a turn, read it back newest-first; a bad row never raises.
    cache.log_chat_turn(chat_session_id="s1", turn_index=0, mode="adhoc",
                        prompt_version="rtcros-v1", user_question="q1",
                        rendered_context="ctx", parsed_answer="a1",
                        cited_entities=["Muse"], source="llm", model="ollama:gemma4:12b",
                        latency_ms=42)
    cache.log_chat_turn(chat_session_id="s1", turn_index=1, mode="story",
                        parsed_answer="a2", source="fallback", latency_ms=5)
    # K2c: tool-loop turns record how many queries ran (depth)
    cache.log_chat_turn(chat_session_id="s1", turn_index=2, mode="adhoc",
                        parsed_answer="a3", source="llm", depth=2,
                        prompt_version="rtcros-tools-v1", latency_ms=1500)
    rows = cache.recent_chat_turns()
    assert [r["turn_index"] for r in rows] == [2, 1, 0]      # newest first
    assert rows[2]["cited_entities"] == ["Muse"] and rows[2]["source"] == "llm"
    assert rows[0]["depth"] == 2 and rows[1]["depth"] is None  # loop vs single-shot
    # best-effort: an unknown kwarg is dropped, a broken write returns -1 not raises
    assert cache.log_chat_turn(chat_session_id="s2", mode="adhoc", source="llm",
                               bogus_field="x") >= 0


def test_queue_rows_running_first_then_worker_fifo(cache):
    # /queue must mirror claim_next's own order (requested_at FIFO) — session 36
    cache.remember_meta([{"spotify_track_id": f"q{i}", "track_name": f"Song {i}",
                          "artist_names": "A"} for i in range(3)])
    cache.enqueue(["q0", "q1", "q2"])
    claimed = cache.claim_next()          # oldest → running
    rows = cache.queue_rows()
    assert [r["id"] for r in rows] == [claimed, "q1", "q2"]  # running first, FIFO after
    assert rows[0]["status"] == "running" and rows[0]["name"] == "Song 0"
    assert {r["status"] for r in rows[1:]} == {"queued"}


def test_active_ids_reports_live_jobs_only(cache):
    cache.enqueue(["a1", "a2"])
    cache.upsert("done1", _FEATURES)      # cached, no live job
    assert cache.active_ids(["a1", "a2", "done1", "ghost"]) == {"a1", "a2"}


def test_remember_meta_threads_art_and_primary_artist(cache):
    cache.remember_meta([{"spotify_track_id": "t1", "track_name": "Song",
                          "album_image_url": "http://art/1", "primary_artist_id": "ar1"}])
    # an update WITHOUT the new fields preserves them (the popularity pattern)
    cache.remember_meta([{"spotify_track_id": "t1", "track_name": "Song v2"}])
    with cache._Session() as s:
        from .models import TrackMeta
        row = s.get(TrackMeta, "t1")
        assert row.album_image_url == "http://art/1"
        assert row.primary_artist_id == "ar1"
        assert row.track_name == "Song v2"


def test_requeue_retryable_converges_instead_of_stalling(cache):
    """A failed-under-cap job was only retried when something re-enqueued that
    id — a dashboard visit or a playlist import. A playlist-imported track is
    never revisited, so 142 of them sat at attempt 1 indefinitely while
    /library advertised "analyzing…" and the queue was empty."""
    cache.remember_meta([{"spotify_track_id": t, "track_name": t,
                          "artist_names": "A"} for t in ("stuck", "dead", "ok")])
    cache.enqueue(["stuck", "dead", "ok"])
    # attempts climb on CLAIM, not on fail — drive the real state machine
    while cache.claim_next() is not None:
        pass
    cache.fail("stuck", "audio acquisition failed")          # attempts -> 1
    cache.fail("ok", "transient")
    for _ in range(MAX_ATTEMPTS):
        cache.fail("dead", "no usable source")
        cache.enqueue(["dead"])
        cache.claim_next()
    cache.fail("dead", "no usable source")                   # dead-lettered
    assert cache.job_states()["stuck"][0] == "failed"

    requeued = cache.requeue_retryable()
    assert "stuck" in requeued and "dead" not in requeued    # cap is respected
    assert cache.job_states()["stuck"][0] == "queued"
    assert cache.job_states()["stuck"][1] == 1, "attempts must NOT reset"
    assert cache.job_states()["dead"][0] == "failed"


def test_requeue_retryable_closes_a_job_whose_track_got_analyzed(cache):
    """If the track was analyzed by some other path since it failed, there is
    nothing to retry — close the job rather than queueing dead work."""
    cache.remember_meta([{"spotify_track_id": "later", "track_name": "L",
                          "artist_names": "A"}])
    cache.enqueue(["later"])
    cache.claim_next()
    cache.fail("later", "transient")
    cache.upsert("later", _FEATURES)                         # analyzed meanwhile
    assert cache.requeue_retryable() == []
    assert cache.job_states()["later"][0] == "done"


def test_requeue_retryable_cannot_hot_loop(cache):
    """Attempts are preserved, so a permanently-failing track walks to
    MAX_ATTEMPTS and dead-letters into the needs-source queue (journal #22)."""
    cache.remember_meta([{"spotify_track_id": "bad", "track_name": "B",
                          "artist_names": "A"}])
    cache.enqueue(["bad"])
    for i in range(1, MAX_ATTEMPTS + 1):
        assert cache.claim_next() == "bad"                   # attempts -> i
        cache.fail("bad", "no usable source")
        expected = ["bad"] if i < MAX_ATTEMPTS else []       # converges at the cap
        assert cache.requeue_retryable() == expected
    assert "bad" in cache.dead_lettered_ids()


def test_searchable_ids_excludes_tracks_with_no_name(cache):
    """The invariant that would have prevented 214 lost tracks: an id with no
    stored name cannot be searched for, so enqueueing it only burns attempts."""
    cache.remember_meta([{"spotify_track_id": "named", "track_name": "Song",
                          "artist_names": "Band"}])
    with cache._Session() as s:
        from .models import TrackMeta
        s.add(TrackMeta(spotify_track_id="bare"))     # membership row, no name
        s.commit()
    assert cache.searchable_ids(["named", "bare", "absent"]) == {"named"}
    assert cache.searchable_ids([]) == set()
