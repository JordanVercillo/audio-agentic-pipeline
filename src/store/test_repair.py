"""
test_repair.py — the D-56 owner-repair engine's invariants.

Synthetic only: probes/downloads are injected, uploads are real bytes built
in-test (a genuine WAV runs the REAL DSP path). The security posture is the
test list: SSRF allowlist, magic-byte sniffing, streamed size cap, duration
hard-rejects before decode, and the Q3 swap discipline (failure writes nothing).
"""

from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest

from .cache import FeatureCache
from .repair import (
    MAX_UPLOAD_BYTES,
    repair_from_link,
    repair_from_upload,
    sniff_audio_format,
    validate_youtube_url,
)


@pytest.fixture
def cache(tmp_path):
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'r.db'}")
    c.upsert("trk", {"tempo_bpm": 140.0, "rms_mean": 0.3,
                     "spectral_centroid_mean": 2000.0})
    c.remember_meta([{"spotify_track_id": "trk", "track_name": "Roots",
                      "artist_names": "WILDS", "duration_ms": 200_000}])
    return c


def _wav_bytes(duration_sec: float = 5.0) -> bytes:
    import soundfile as sf

    from ..dsp.audio_loader import generate_test_signal
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=duration_sec)
    buf = io.BytesIO()
    sf.write(buf, sig.waveform, sig.sr, format="WAV")
    return buf.getvalue()


# ── the SSRF allowlist ───────────────────────────────────────────────────────
def test_validate_youtube_url_allowlist():
    assert validate_youtube_url("https://www.youtube.com/watch?v=abc") is not None
    assert validate_youtube_url("https://youtu.be/abc") is not None
    assert validate_youtube_url("https://music.youtube.com/watch?v=abc") is not None
    for bad in ("javascript:alert(1)", "file:///etc/passwd",
                "https://evil.com/watch?v=abc", "https://youtube.com.evil.com/x",
                "ftp://youtube.com/x", "", None, "not a url"):
        assert validate_youtube_url(bad) is None, bad


# ── magic bytes, never extensions ────────────────────────────────────────────
def test_sniff_audio_format():
    assert sniff_audio_format(b"ID3\x04" + b"\x00" * 12) == "mp3"
    assert sniff_audio_format(b"\xff\xfb" + b"\x00" * 14) == "mp3"
    assert sniff_audio_format(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert sniff_audio_format(b"fLaC" + b"\x00" * 12) == "flac"
    assert sniff_audio_format(b"\x00\x00\x00 ftypM4A " + b"\x00" * 4) == "m4a"
    assert sniff_audio_format(b"MZ\x90\x00" + b"\x00" * 12) is None       # a PE exe
    assert sniff_audio_format(b"<!DOCTYPE html>!") is None
    assert sniff_audio_format(b"") is None


# ── link repair ──────────────────────────────────────────────────────────────
def test_link_repair_hard_rejects_wrong_duration_before_download(cache, tmp_path):
    downloads: list = []
    ok, msg = repair_from_link(
        cache, "trk", "https://youtu.be/mix", audio_dir=tmp_path / "a",
        spectrogram_dir=tmp_path / "s",
        probe=lambda u: {"id": "mix", "title": "2 Hour Set", "duration": 7200},
        download=lambda *a: downloads.append(a))
    assert not ok and "wrong version" in msg
    assert downloads == []                                  # rejected pre-download
    assert cache.provenance_for("trk") is None


def test_link_repair_refuses_non_youtube(cache, tmp_path):
    ok, msg = repair_from_link(cache, "trk", "https://evil.com/watch?v=x",
                               audio_dir=tmp_path / "a",
                               spectrogram_dir=tmp_path / "s",
                               probe=lambda u: pytest.fail("must not probe"),
                               download=lambda *a: pytest.fail("must not download"))
    assert not ok and "YouTube" in msg


def test_link_repair_happy_path_swaps_and_records_manual_provenance(cache, tmp_path):
    import soundfile as sf

    from ..dsp.audio_loader import generate_test_signal

    def fake_download(url, tid, dest):
        sig = generate_test_signal(frequency_hz=220.0, duration_sec=5.0)
        Path(dest).mkdir(parents=True, exist_ok=True)
        out = Path(dest) / f"{tid}.wav"
        sf.write(out, sig.waveform, sig.sr)
        return out

    before_tempo = cache.get(["trk"])["trk"]["tempo_bpm"]
    ok, msg = repair_from_link(
        cache, "trk", "https://www.youtube.com/watch?v=real",
        audio_dir=tmp_path / "a", spectrogram_dir=tmp_path / "s",
        probe=lambda u: {"id": "real", "title": "Roots (Official)",
                         "channel": "WILDS", "duration": 201},
        download=fake_download)
    assert ok, msg
    assert cache.get(["trk"])["trk"]["tempo_bpm"] != before_tempo   # a true swap
    p = cache.provenance_for("trk")
    assert p["matcher_version"] == "manual-link"
    assert p["youtube_title"] == "Roots (Official)"
    assert p["match_confidence"] is None                    # human-vouched, no score
    assert not (tmp_path / "a" / "trk.wav").exists()        # transient audio cleaned


# ── upload repair ────────────────────────────────────────────────────────────
def test_upload_rejects_non_audio_bytes(cache, tmp_path):
    ok, msg = repair_from_upload(cache, "trk", io.BytesIO(b"MZ\x90\x00" + b"E" * 100),
                                 audio_dir=tmp_path / "a",
                                 spectrogram_dir=tmp_path / "s")
    assert not ok and "unrecognized audio format" in msg
    assert cache.provenance_for("trk") is None


def test_upload_enforces_size_cap_while_streaming(cache, tmp_path):
    # the cap is enforced against the STREAM (never buffer-then-check); use a
    # small explicit cap so the test doesn't allocate the real ceiling
    big = io.BytesIO(b"ID3\x04" + b"\x00" * (2 << 20))
    ok, msg = repair_from_upload(cache, "trk", big, audio_dir=tmp_path / "a",
                                 spectrogram_dir=tmp_path / "s",
                                 max_bytes=1 << 20)
    assert not ok and "MB cap" in msg
    assert not list((tmp_path / "a").glob("trk.*"))         # partial file cleaned


def test_upload_cap_fits_a_lossless_master(cache, tmp_path):
    # D-56 is OWNER-only, and the tracks needing it are exactly those with no
    # YouTube source — indie masters arrive as lossless WAV (~10.6 MB/min), so
    # D-45's public-facing 20 MB would reject a legitimate 3-minute master.
    assert MAX_UPLOAD_BYTES >= 100 * 1024 * 1024


def test_upload_happy_path_real_wav_runs_real_dsp(cache, tmp_path, monkeypatch):
    # ffprobe may not see a plausible duration for the 5s test tone vs the
    # 200s track — the duration guard compares against Spotify's length, so
    # give the track a matching duration for the happy path.
    cache.remember_meta([{"spotify_track_id": "trk", "track_name": "Roots",
                          "artist_names": "WILDS", "duration_ms": 5_000}])
    before = copy.deepcopy(cache.get(["trk"])["trk"])
    ok, msg = repair_from_upload(cache, "trk", io.BytesIO(_wav_bytes(5.0)),
                                 audio_dir=tmp_path / "a",
                                 spectrogram_dir=tmp_path / "s")
    assert ok, msg
    assert cache.get(["trk"])["trk"] != before              # features swapped
    p = cache.provenance_for("trk")
    assert p["matcher_version"] == "manual-upload"
    assert p["audio_format"] == "wav"
    assert p["youtube_url"] is None
    assert p["youtube_title"] == "Owner-supplied audio file"  # constant, no filename
    assert (tmp_path / "s" / "trk.png").exists()            # spectrogram rendered


def test_accepted_upload_is_RETAINED_rejected_is_not(cache, tmp_path):
    # V2: an owner upload is the ONLY copy (no external source), so an accepted
    # file is kept for playback + future re-extraction; a rejected one is not.
    from .repair import find_owner_audio
    keep = tmp_path / "owner_audio"
    cache.remember_meta([{"spotify_track_id": "trk", "track_name": "Roots",
                          "artist_names": "WILDS", "duration_ms": 5_000}])
    ok, msg = repair_from_upload(cache, "trk", io.BytesIO(_wav_bytes(5.0)),
                                 audio_dir=tmp_path / "a",
                                 spectrogram_dir=tmp_path / "s", keep_dir=keep)
    assert ok, msg
    kept = find_owner_audio(keep, "trk")
    assert kept is not None and kept.suffix == ".wav" and kept.stat().st_size > 0
    assert not list((tmp_path / "a").glob("trk.*"))     # scratch still cleaned

    # a rejected upload leaves nothing behind
    ok2, _ = repair_from_upload(cache, "trk", io.BytesIO(b"MZ\x90\x00" + b"E" * 64),
                                audio_dir=tmp_path / "a",
                                spectrogram_dir=tmp_path / "s",
                                keep_dir=tmp_path / "owner_audio2")
    assert not ok2 and find_owner_audio(tmp_path / "owner_audio2", "trk") is None


def test_owner_audio_path_resists_traversal():
    from .repair import owner_audio_path
    p = owner_audio_path(Path("/keep"), "../../etc/passwd", "mp3")
    assert p.parent == Path("/keep") and "passwd" in p.name


def test_repair_refreshes_the_derived_planes(cache, tmp_path):
    # Live bug: a repair swapped TrackFeatures but /explore, /recommend and the
    # chat read track_perceptual + the marts, which kept the WRONG-audio
    # numbers until something else rebuilt. Same class as the O3
    # compute-vs-table trap — fixing one layer isn't fixing the read path.
    cache.remember_meta([{"spotify_track_id": "trk", "track_name": "Roots",
                          "artist_names": "WILDS", "duration_ms": 5_000}])
    marts = tmp_path / "marts"
    rebuilt: list = []
    import src.store.perceptual as perc
    orig = perc.rebuild_marts
    perc.rebuild_marts = lambda c, d: rebuilt.append(Path(d)) or orig(c, d)
    try:
        ok, msg = repair_from_upload(cache, "trk", io.BytesIO(_wav_bytes(5.0)),
                                     audio_dir=tmp_path / "a",
                                     spectrogram_dir=tmp_path / "s",
                                     marts_dir=marts)
    finally:
        perc.rebuild_marts = orig
    assert ok, msg
    assert rebuilt == [marts]                    # the derived planes were rebuilt
    # …and a rebuild failure must NOT undo a good repair (best-effort)
    perc_fail = perc.rebuild_marts
    perc.rebuild_marts = lambda c, d: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        ok2, _ = repair_from_upload(cache, "trk", io.BytesIO(_wav_bytes(5.0)),
                                    audio_dir=tmp_path / "a",
                                    spectrogram_dir=tmp_path / "s",
                                    marts_dir=marts)
    finally:
        perc.rebuild_marts = perc_fail
    assert ok2                                    # swap still succeeded


def test_upload_duration_mismatch_hard_rejects(cache, tmp_path):
    # track says 200s; the uploaded tone is 5s*… make the FILE long instead:
    # a 5s file against a 200s track is SHORT (allowed — implausible only when
    # LONGER), so test the long direction: 500s file vs 200s track. Building a
    # 500s wav is slow — shrink the track instead: 60s track, 500s file? Still
    # slow. Use a 30s file vs a 10s track (3x + >120s? 30 vs 10 → ratio 3 but
    # extra 20s < 120 → NOT implausible). The rule needs BOTH: use 300s file…
    # too slow. So: monkeypatch ffprobe to lie long — the guard fires pre-decode.
    from . import repair as rp
    cache.remember_meta([{"spotify_track_id": "trk", "track_name": "Roots",
                          "artist_names": "WILDS", "duration_ms": 200_000}])
    import unittest.mock as mock
    with mock.patch.object(rp, "_ffprobe_duration", return_value=7200.0):
        ok, msg = repair_from_upload(cache, "trk", io.BytesIO(_wav_bytes(5.0)),
                                     audio_dir=tmp_path / "a",
                                     spectrogram_dir=tmp_path / "s")
    assert not ok and "wrong version" in msg
    assert cache.provenance_for("trk") is None
