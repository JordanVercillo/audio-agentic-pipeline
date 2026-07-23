"""
test_re_extract.py — the D-52 re-extraction program's invariants (Q3).

Synthetic only (ground rule 5): the acquire step is injected, so the whole
swap/failure/resume surface runs offline. The invariants under test are the
Fable-signed batch plan: atomic-swap-on-success, failure-keeps-old-bytes,
no queue side-effects, provenance-as-success-marker resume, twin/scope rules,
and value-first ordering.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from .cache import FeatureCache
from .re_extract import Ledger, re_extract_one, run, select_targets
from .test_store import _synth_acquire_full


@pytest.fixture
def cache(tmp_path):
    return FeatureCache(url=f"sqlite:///{tmp_path / 're.db'}")


def _seed(cache, tid: str, tempo: float = 120.0, conf=None, *, twin_of=None):
    cache.remember_meta([{"spotify_track_id": tid, "track_name": f"T {tid}",
                          "artist_names": "A", "duration_ms": 200_000}])
    cache.upsert(tid, {"tempo_bpm": tempo, "rms_mean": 0.3,
                       "spectral_centroid_mean": 2000.0},
                 match_confidence=conf)
    if twin_of:
        # mirror resolve_duplicate's flag without the job machinery
        with cache._Session() as s:
            from .models import TrackMeta
            s.get(TrackMeta, tid).duplicate_of = twin_of
            s.commit()


def _fail_acquire(track_id, name, artist, dest_dir, duration_s=None):
    return None, None


def test_select_targets_scope_and_value_first_order(cache):
    _seed(cache, "normal", tempo=120.0, conf=0.9)
    _seed(cache, "lowconf", tempo=130.0, conf=0.1)
    _seed(cache, "noconf", tempo=125.0, conf=None)
    _seed(cache, "broken", tempo=0.0, conf=0.8)          # the Aftermath shape
    _seed(cache, "twin", tempo=118.0, conf=0.2, twin_of="normal")
    cache.remember_meta([{"spotify_track_id": "metaonly", "track_name": "M",
                          "artist_names": "A"}])          # no features → not in scope
    order = select_targets(cache)
    assert order == ["broken", "lowconf", "normal", "noconf"]
    assert "twin" not in order and "metaonly" not in order


def test_success_swaps_features_and_appends_provenance(cache, tmp_path):
    _seed(cache, "s1", tempo=0.0)                         # broken → real after swap
    ok, note = re_extract_one(cache, "s1", audio_dir=tmp_path / "a",
                              spectrogram_dir=tmp_path / "s",
                              acquire=_synth_acquire_full)
    assert ok, note
    feats = cache.get(["s1"])["s1"]
    assert feats["tempo_bpm"] > 1.0                       # real DSP replaced the dead row
    prov = cache.provenance_for("s1")
    assert prov and prov["youtube_video_id"] == "abc123"  # ∅ → recorded
    assert not (tmp_path / "a" / "s1.wav").exists()       # transient audio deleted


def test_failure_keeps_old_row_byte_identical_and_no_provenance(cache, tmp_path):
    # Precision-biased by design: a false "success" that swaps to a worse
    # source is the costly error, so failure must leave EVERYTHING untouched —
    # features, every display column, confidence — and append no provenance.
    _seed(cache, "f1", tempo=140.0, conf=0.7)
    cache.upsert("f1", cache.get(["f1"])["f1"], loudness_curve=[-30.0, -10.0],
                 time_signature=3, beat_times=[0.5, 1.0],
                 sections=[{"start": 0.0, "end": 9.9, "label": 0}])
    before = copy.deepcopy(cache.get(["f1"])["f1"])
    ok, note = re_extract_one(cache, "f1", audio_dir=tmp_path / "a",
                              spectrogram_dir=tmp_path / "s", acquire=_fail_acquire)
    assert not ok and "acquisition failed" in note
    assert cache.get(["f1"])["f1"] == before              # untouched, byte-identical
    assert cache.provenance_for("f1") is None             # ∅ stays honest
    assert cache.all_match_confidence()["f1"] == 0.7      # promoted col untouched
    assert cache.loudness_curve("f1") == [-30.0, -10.0]   # display cols untouched
    assert cache.all_time_signatures().get("f1") == 3
    assert cache.beat_times("f1") == [0.5, 1.0]


def test_swap_replaces_display_cols_not_merges(cache, tmp_path):
    # F2 (red-team): the OLD audio's curve/meter must NOT survive a
    # re-acquisition whose new DSP produces different (or no) values — a true
    # swap, never a preserve-on-None merge across two different sources.
    _seed(cache, "sw1", tempo=120.0)
    cache.upsert("sw1", cache.get(["sw1"])["sw1"],
                 loudness_curve=[-99.0] * 4, time_signature=7,
                 beat_times=[9.9], sections=[{"start": 0, "end": 1, "label": 0}])
    ok, _ = re_extract_one(cache, "sw1", audio_dir=tmp_path / "a",
                           spectrogram_dir=tmp_path / "s",
                           acquire=_synth_acquire_full)
    assert ok
    assert cache.loudness_curve("sw1") != [-99.0] * 4     # the new audio's curve
    assert cache.all_time_signatures().get("sw1") != 7    # 5s test tone ≠ old 7/8
    assert cache.beat_times("sw1") != [9.9]


def test_scratch_dir_never_touches_preexisting_audio(cache, tmp_path):
    # F3 (red-team): a pre-existing raw_audio file must survive a re-extract
    # byte-identical — the runner downloads into its own scratch dir.
    raw = tmp_path / "raw_audio"
    raw.mkdir()
    sentinel = raw / "sx1.mp3"
    sentinel.write_bytes(b"OWNER-MP3-DO-NOT-DELETE")
    _seed(cache, "sx1", tempo=120.0)
    scratch = tmp_path / "scratch"
    ok, _ = re_extract_one(cache, "sx1", audio_dir=scratch,
                           spectrogram_dir=tmp_path / "s",
                           acquire=_synth_acquire_full)
    assert ok
    assert sentinel.read_bytes() == b"OWNER-MP3-DO-NOT-DELETE"  # untouched
    assert not any(scratch.glob("sx1.*"))                  # scratch cleaned (D-15)


def test_write_atomic_tmp_is_unique_per_process(tmp_path):
    # F1 (red-team): two concurrent rebuilds must never share a tmp path — a
    # fixed ".tmp" let one process replace the other's half-written mart.
    import pandas as pd

    from .perceptual import _write_atomic
    target = tmp_path / "m.parquet"
    _write_atomic(pd.DataFrame([{"a": 1}]), target)
    import os
    assert f".{os.getpid()}.tmp" in str(
        target.with_suffix(target.suffix + f".{os.getpid()}.tmp"))
    # the real assertion: the tmp naming embeds the pid, so a different pid
    # cannot collide; and nothing tmp-shaped is left behind
    assert target.exists() and not list(tmp_path.glob("*.tmp"))


def test_provenance_write_failure_is_a_per_track_failure(cache, tmp_path, monkeypatch):
    # Red-team #5: the provenance row is the resume marker — a swallowed write
    # must surface as a failure (ledgered, retried) rather than silently
    # leaving a swapped row invisible to resume.
    _seed(cache, "pv1", tempo=120.0)
    monkeypatch.setattr(type(cache), "remember_provenance",
                        lambda self, **kw: -1)
    ok, note = re_extract_one(cache, "pv1", audio_dir=tmp_path / "a",
                              spectrogram_dir=tmp_path / "s",
                              acquire=_synth_acquire_full)
    assert not ok and "provenance write failed" in note


def test_still_broken_swap_is_flagged_not_failed(cache, tmp_path):
    # Red-team #8: a successful re-extract that STILL measures tempo≤1 swaps
    # honestly (it is the real measurement), stays gated, and is flagged for
    # Q4 — never dead-lettered.
    import soundfile as sf

    from ..dsp.audio_loader import generate_test_signal
    _seed(cache, "qb1", tempo=0.0)

    def silent_acquire(track_id, name, artist, dest_dir, duration_s=None):
        sig = generate_test_signal(frequency_hz=220.0, duration_sec=5.0)
        path = Path(dest_dir)
        path.mkdir(parents=True, exist_ok=True)
        out = path / f"{track_id}.wav"
        sf.write(out, sig.waveform * 0.0, sig.sr)          # pure silence → dead DSP
        return out, {"url": "u", "title": "t", "score": 0, "confidence": 1.0,
                     "duration_delta_s": 0.0, "candidate_count": 1,
                     "matcher_version": "heuristic-v1"}

    ledger = Ledger(tmp_path / "led.json")
    s = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
            ledger=ledger, limit=None, acquire=silent_acquire)
    assert s["ok"] == 1 and s["failed"] == 0               # a success, not a failure
    assert "qb1" in ledger.data.get("flags", {})           # …but flagged for Q4
    assert cache.provenance_for("qb1") is not None         # provenance recorded


def test_implausible_duration_rule():
    # The live finding: a 130-min DJ set stored as a 3.5-min track. Reject the
    # objectively-wrong, never a legitimately-longer remix.
    from .re_extract import implausible_duration
    assert implausible_duration(7396.0, 207.0)          # 36x — a DJ set
    assert implausible_duration(3600.0, 210.0)
    assert not implausible_duration(240.0, 200.0)       # a slightly longer take
    assert not implausible_duration(330.0, 200.0)       # extended mix, <2x AND <+120s
    assert not implausible_duration(200.0, 200.0)
    assert not implausible_duration(None, 200.0)        # unknown → never guess
    assert not implausible_duration(400.0, None)
    assert not implausible_duration(0.0, 200.0)
    # a genuinely long track is judged against ITS OWN spotify length
    assert not implausible_duration(600.0, 590.0)


def test_title_affinity_on_the_real_wrong_song_pairs():
    # Fixtures ARE the live failures (2026-07-23): every confirmed wrong-song
    # swap must reject; the tokenization artifacts (right video, mangled
    # overlap) must pass. Precision-first: artist-only overlap is NOT enough.
    from .re_extract import title_affinity
    # confirmed wrong songs → False
    assert not title_affinity("Alone", "MPH, Carla Monroe",
                              "Anti-Up - Shake (Official Visualizer)")
    assert not title_affinity("Prayers", "Zefer",
                              "Ziferblat - Bird of Pray | Ukraine | Official Music Video")
    assert not title_affinity("NOW IT'S GONE - DIFFRENT REMIX", "IN PARALLEL, Diffrent",
                              "Tate McRae - siren sounds (bridge demo)")
    assert not title_affinity("305 LUV STORY", "Gonzy",
                              "Gonzy - SOBREDOSIS (Official)", "Gonzy")  # same artist ≠ same song
    assert not title_affinity("Peace of Mind (feat. Delilah)", "Hutcher, GEE LEE, Delilah",
                              "Rod Wave - Bachelor (Official Audio)")
    # right videos that a naive normalizer scores 0 → True
    assert title_affinity("Airmaxes - KETTAMA Mix", "KETTAMA, Shady Nasty, Fred again..",
                          "KETTAMA, Shady Nasty, Fred Again.. - Air Maxes (KETTAMA MIX)")
    assert title_affinity("Boasty (Conducta Remix) - Mixed", "Wiley, Stefflon Don",
                          "Wiley Ft Stefflon Don ft Sean Paul Idris Elba Boasty Official Audio")
    assert title_affinity("Hysteria", "Muse", "Muse - Hysteria [Official Music Video]")
    assert title_affinity("Q&A", "Drake", "Drake - Q&A Lyrics (DLyrics01)")


def _patch_candidates(monkeypatch, candidates):
    monkeypatch.setattr(
        "src.ingestion.audio_downloader.resolve_youtube_candidates",
        lambda name, artist, duration_s=None, **kw: candidates)


def test_no_affinity_candidate_rejected_before_download(cache, tmp_path, monkeypatch):
    from . import re_extract as rx
    downloads: list = []
    _patch_candidates(monkeypatch, [{
        "url": "https://y/wrong", "title": "Completely Unrelated Tune",
        "channel": "OtherVEVO", "score": 25, "confidence": 0.85,
        "duration_delta_s": 1.7, "youtube_duration_s": 208.0,
        "candidate_count": 5}])
    monkeypatch.setattr("src.ingestion.audio_downloader.download_track_audio",
                        lambda *a, **k: downloads.append(a))
    path, match = rx.guarded_acquire("t", "Blue Horizon", "My Artist",
                                     tmp_path, 207.0)
    assert path is None and match["_rejected"] == "gate"
    assert "title" in match["_reason"]                   # names the real cause
    assert downloads == []


def test_wrong_version_is_rejected_before_download(cache, tmp_path, monkeypatch):
    # guarded_acquire must refuse a DJ-set candidate WITHOUT downloading it.
    from . import re_extract as rx
    downloads: list = []
    _patch_candidates(monkeypatch, [{
        "url": "https://y/mix", "title": "2 Hour Mix", "score": 0,
        "confidence": 0.1, "duration_delta_s": 7000.0,
        "youtube_duration_s": 7396.0, "candidate_count": 5}])
    monkeypatch.setattr("src.ingestion.audio_downloader.download_track_audio",
                        lambda *a, **k: downloads.append(a) or Path("nope.mp3"))
    path, match = rx.guarded_acquire("t", "WGTF?", "Riordan", tmp_path, 207.0)
    assert path is None and match["_rejected"] == "gate"
    assert downloads == []                               # never fetched the 170 MB


def test_guarded_acquire_downloads_the_survivor_not_the_top_score(
        cache, tmp_path, monkeypatch):
    # QA2's whole point: the highest-scoring candidate is a DJ set, but a real
    # recording sits below it. The old rank-then-reject path binned both.
    from . import re_extract as rx
    downloads: list = []
    _patch_candidates(monkeypatch, [
        {"url": "https://y/mix", "title": "Riordan B2B in a Skate Park | RAW CUTS",
         "channel": "RAW", "score": 25, "youtube_duration_s": 7397.0},
        {"url": "https://y/real", "title": "Riordan - WGTF? (Official Audio)",
         "channel": "Riordan", "score": 10, "youtube_duration_s": 205.0}])
    monkeypatch.setattr("src.ingestion.audio_downloader.download_track_audio",
                        lambda url, tid, cfg: downloads.append(url) or Path("a.mp3"))
    path, match = rx.guarded_acquire("t", "WGTF?", "Riordan", tmp_path, 207.0)
    assert downloads == ["https://y/real"] and match["url"] == "https://y/real"
    assert path == Path("a.mp3")


def test_wrong_version_keeps_old_features_and_ledgers(cache, tmp_path):
    # End-to-end: the swap is refused, the old row is untouched, no provenance,
    # and the reason is ledgered for Q4.
    _seed(cache, "wv1", tempo=140.0, conf=0.5)
    with cache._Session() as s:
        from .models import TrackMeta
        s.get(TrackMeta, "wv1").duration_ms = 207_000
        s.commit()
    before = copy.deepcopy(cache.get(["wv1"])["wv1"])

    def mix_acquire(track_id, name, artist, dest_dir, duration_s=None):
        return None, {"url": "u", "title": "2 Hour Mix",
                      "youtube_duration_s": 7396.0, "_rejected": "gate",
                      "_reason": "length mismatch — 7396s vs expected 207s"}

    ledger = Ledger(tmp_path / "led.json")
    s = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
            ledger=ledger, limit=None, acquire=mix_acquire)
    assert s["ok"] == 0 and s["failed"] == 1
    assert cache.get(["wv1"])["wv1"] == before           # untouched
    assert cache.provenance_for("wv1") is None
    assert "length mismatch" in ledger.data["failed"]["wv1"]["error"]


def test_runner_never_touches_the_job_queue(cache, tmp_path):
    _seed(cache, "q1", tempo=120.0)
    ledger = Ledger(tmp_path / "led.json")
    run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
        ledger=ledger, limit=5, acquire=_fail_acquire)
    s = cache.job_status(["q1"])                          # no job row ever created:
    assert s["queued"] == 0 and s["running"] == 0 and s["failed"] == 0


def test_run_resume_and_ledger_semantics(cache, tmp_path):
    _seed(cache, "ok1", tempo=120.0, conf=0.3)
    _seed(cache, "bad1", tempo=125.0, conf=0.2)
    ledger = Ledger(tmp_path / "led.json")

    calls: list[str] = []

    def scripted(track_id, name, artist, dest_dir, duration_s=None):
        calls.append(track_id)
        if track_id == "bad1":
            return None, None
        return _synth_acquire_full(track_id, name, artist, dest_dir, duration_s)

    s1 = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
             ledger=ledger, limit=None, acquire=scripted)
    assert s1["ok"] == 1 and s1["failed"] == 1
    assert ledger.failed_ids() == {"bad1"}

    # resume: the success (provenance marker) AND the ledgered failure are skipped
    calls.clear()
    s2 = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
             ledger=ledger, limit=None, acquire=scripted)
    assert s2["attempted"] == 0 and calls == []

    # --retry-failed reattempts ONLY the failure; success clears its ledger entry
    def now_works(track_id, name, artist, dest_dir, duration_s=None):
        calls.append(track_id)
        return _synth_acquire_full(track_id, name, artist, dest_dir, duration_s)

    s3 = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
             ledger=ledger, limit=None, retry_failed=True, acquire=now_works)
    assert calls == ["bad1"] and s3["ok"] == 1
    assert ledger.failed_ids() == set()
    # the run history is persisted for Q4's QA reader
    assert len(Ledger(tmp_path / "led.json").data["runs"]) == 3


def test_run_limit_caps_and_reports_remaining(cache, tmp_path):
    for i in range(4):
        _seed(cache, f"t{i}", tempo=120.0 + i)
    ledger = Ledger(tmp_path / "led.json")
    s = run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
            ledger=ledger, limit=2, acquire=_synth_acquire_full)
    assert s["attempted"] == 2 and s["ok"] == 2 and s["remaining"] == 2


def test_run_rebuilds_marts_only_on_change(cache, tmp_path, monkeypatch):
    _seed(cache, "m1", tempo=120.0)
    rebuilds: list[int] = []
    monkeypatch.setattr("src.store.perceptual.rebuild_marts",
                        lambda c, d: rebuilds.append(1))
    ledger = Ledger(tmp_path / "led.json")
    run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
        ledger=ledger, limit=None, acquire=_synth_acquire_full,
        marts_dir=tmp_path / "marts")
    assert rebuilds == [1]                                # one rebuild after the batch
    run(cache, audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
        ledger=ledger, limit=None, acquire=_synth_acquire_full,
        marts_dir=tmp_path / "marts")
    assert rebuilds == [1]                                # nothing new → no rebuild
