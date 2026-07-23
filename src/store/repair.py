"""
repair.py — owner-driven acquisition repair (D-56, Epic Q).

When the automatic matcher can't reliably find a track's audio (the ledger's
wrong-version / no-affinity rejections, or tracks that simply aren't on
YouTube), the OWNER supplies the source: a pasted YouTube link, or an audio
file upload. A human vouches for IDENTITY; the machine still vouches for
PLAUSIBILITY — the same duration validation runs, and a mismatch HARD-REJECTS
(owner-ratified: a wrong-length source corrupts features regardless of who
vouched for it).

Security posture (D-45, reviewed):
    - Links: scheme + host ALLOWLIST (YouTube only) before anything touches
      yt-dlp — no SSRF, no arbitrary-protocol fetches. Duration probed and
      validated BEFORE the download.
    - Uploads: size cap enforced while STREAMING (never buffer-then-check),
      container sniffed by MAGIC BYTES (an extension is attacker-chosen text),
      duration probed by ffprobe BEFORE any decode, and `load_audio`'s own
      bounds re-validate after. The stored display title is a CONSTANT — an
      untrusted filename never reaches a template.
    - Both paths end in the Q3 swap discipline: upsert(replace_display=True)
      only after full DSP; any failure leaves the old row byte-identical and
      writes no provenance. matcher_version records manual-link/manual-upload
      so Q4's QA can segment human-vouched rows.
    - This module NEVER writes the runner's ledger (single-writer: the runner
      owns that file); a successful repair's provenance row clears the ledger
      entry via the runner's provenance-wins reconciliation.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.parse import urlparse

from .cache import FeatureCache
from .extractor import DSP_VERSION, make_mel_spectrogram
from .re_extract import implausible_duration

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024          # D-45: 20 MB cap
_ALLOWED_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
})
# magic-byte signatures — the CONTENT decides the format, never the filename
_UPLOAD_TITLE = "Owner-supplied audio file"   # constant: no untrusted filename in templates


def validate_youtube_url(url: Optional[str]) -> Optional[str]:
    """The pasted link, or None if it isn't plainly a YouTube watch URL.
    Allowlist, not blocklist: only http(s) + known YouTube hosts survive —
    everything else (javascript:, file:, an attacker's host) is refused
    before yt-dlp ever sees it."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    if p.hostname.lower() not in _ALLOWED_HOSTS:
        return None
    return p.geturl()


def sniff_audio_format(head: bytes) -> Optional[str]:
    """Container from the first bytes: mp3 | wav | flac | m4a, else None."""
    if len(head) < 12:
        return None
    if head[:3] == b"ID3" or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def _ffprobe_duration(path: Path) -> Optional[float]:
    """Container-declared duration BEFORE any decode (a codec bomb should be
    rejected by arithmetic, not survived by decoding). None when ffprobe is
    unavailable/undecidable — load_audio's own bounds still apply after."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30, check=False)
        return float(out.stdout.strip()) if out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _swap(cache: FeatureCache, track_id: str, audio_path: Path,
          spectrogram_dir: Path, expected_s: Optional[float],
          provenance: dict[str, Any]) -> tuple[bool, str]:
    """The shared tail: load → post-load duration backstop → DSP →
    atomic swap → provenance. Failure writes NOTHING (Q3 discipline)."""
    from ..dsp.audio_loader import load_audio
    from ..dsp.feature_extractor import extract_features

    signal = load_audio(audio_path)
    actual_s = getattr(signal, "duration_sec", None)
    if implausible_duration(actual_s, expected_s):
        return False, (f"rejected: audio is {actual_s or 0:.0f}s but this track "
                       f"is {expected_s or 0:.0f}s on Spotify — wrong version")
    tf = extract_features(signal)
    features = tf.to_summary_dict()
    spec_uri = make_mel_spectrogram(signal, Path(spectrogram_dir) / f"{track_id}.png")
    cache.upsert(track_id, features, spectrogram_uri=str(spec_uri),
                 source=provenance.get("source", "manual"),
                 dsp_version=DSP_VERSION,
                 loudness_curve=tf.loudness_curve_points(),
                 time_signature=tf.time_signature,
                 beat_times=tf.beat_times_list(),
                 sections=tf.sections_list(),
                 match_confidence=None,       # human-vouched — no heuristic score
                 replace_display=True)
    pid = cache.remember_provenance(
        spotify_track_id=track_id, dsp_version=DSP_VERSION,
        audio_format=provenance.get("audio_format"),
        audio_bitrate_kbps=provenance.get("audio_bitrate_kbps"),
        youtube_url=provenance.get("youtube_url"),
        youtube_video_id=provenance.get("youtube_video_id"),
        youtube_title=provenance.get("youtube_title"),
        channel=provenance.get("channel"),
        youtube_duration_s=provenance.get("youtube_duration_s"),
        matcher_version=provenance.get("matcher_version", "manual"))
    if pid <= 0:
        return False, "provenance write failed (features already swapped) — retry"
    return True, "repaired"


def repair_from_link(cache: FeatureCache, track_id: str, url: str, *,
                     audio_dir: Path, spectrogram_dir: Path,
                     probe=None, download=None) -> tuple[bool, str]:
    """Owner-pasted YouTube link → validated swap. `probe`/`download` are
    injectable for tests (ground rule 5). Never raises."""
    audio_path: Optional[Path] = None
    try:
        meta = cache.get_meta(track_id)
        if not meta:
            return False, "unknown track"
        clean = validate_youtube_url(url)
        if clean is None:
            return False, "not a YouTube link — only youtube.com / youtu.be URLs are accepted"
        expected_s = (meta.get("duration_ms") or 0) / 1000.0 or None

        if probe is None:
            def probe(u):  # pragma: no cover — thin yt-dlp shim, tests inject
                import yt_dlp
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                       "skip_download": True}) as ydl:
                    return ydl.extract_info(u, download=False)
        info = probe(clean) or {}
        vid_len = info.get("duration")
        # HARD-REJECT before the download (owner-ratified): human identity,
        # machine plausibility.
        if implausible_duration(vid_len, expected_s):
            return False, (f"rejected: that video is {vid_len or 0:.0f}s but this "
                           f"track is {expected_s or 0:.0f}s on Spotify — wrong version")

        if download is None:
            def download(u, tid, dest):  # pragma: no cover — thin shim, tests inject
                from ..ingestion.audio_downloader import (
                    DownloadConfig,
                    download_track_audio,
                )
                return download_track_audio(u, tid, DownloadConfig(output_dir=Path(dest)))
        audio_path = download(clean, track_id, audio_dir)
        if audio_path is None or not Path(audio_path).exists():
            return False, "download failed"
        return _swap(cache, track_id, Path(audio_path), spectrogram_dir, expected_s, {
            "source": "youtube", "matcher_version": "manual-link",
            "youtube_url": clean, "youtube_video_id": info.get("id"),
            "youtube_title": info.get("title"), "channel": info.get("channel")
            or info.get("uploader"),
            "youtube_duration_s": float(vid_len) if vid_len else None,
            "audio_format": "mp3", "audio_bitrate_kbps": 192})
    except Exception as exc:  # noqa: BLE001 — a repair must never 500 the app
        logger.warning("repair_from_link failed for %s: %s", track_id, exc)
        return False, f"repair failed: {exc}"
    finally:
        if audio_path is not None:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass


def owner_audio_path(audio_dir: Path, track_id: str, fmt: str) -> Path:
    """Where a KEPT owner upload lives. `.name` strips any traversal attempt —
    the id is base62-guarded upstream, this is defense in depth."""
    return Path(audio_dir) / f"{Path(track_id).name}.{fmt}"


def find_owner_audio(audio_dir: Path, track_id: str) -> Optional[Path]:
    """The retained upload for a track, if any (V2 playback)."""
    for fmt in ("mp3", "wav", "flac", "m4a"):
        p = owner_audio_path(audio_dir, track_id, fmt)
        if p.exists():
            return p
    return None


def repair_from_upload(cache: FeatureCache, track_id: str, stream: BinaryIO, *,
                       audio_dir: Path, spectrogram_dir: Path,
                       max_bytes: int = MAX_UPLOAD_BYTES,
                       keep_dir: Optional[Path] = None) -> tuple[bool, str]:
    """Owner-uploaded audio file → validated swap. The stream is read in
    chunks against the cap (never buffer-then-check); the container is
    sniffed from magic bytes; duration is validated BEFORE decode.

    V2 — `keep_dir` RETAINS the accepted file. D-15 makes audio transient
    because YouTube is the durable source; an owner upload has NO external
    source, so deleting it would destroy the only copy (no future
    re-extraction, and nothing to play back for verification). Rejected
    uploads are still deleted. Never raises."""
    audio_path: Optional[Path] = None
    try:
        meta = cache.get_meta(track_id)
        if not meta:
            return False, "unknown track"
        expected_s = (meta.get("duration_ms") or 0) / 1000.0 or None

        head = stream.read(16)
        fmt = sniff_audio_format(head)
        if fmt is None:
            return False, ("unrecognized audio format — mp3/wav/flac/m4a only "
                           "(the file's content decides, not its name)")
        audio_dir = Path(audio_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{track_id}.{fmt}"
        total = len(head)
        with open(audio_path, "wb") as f:
            f.write(head)
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return False, f"file exceeds the {max_bytes // (1 << 20)} MB cap"
                f.write(chunk)

        probed = _ffprobe_duration(audio_path)
        if implausible_duration(probed, expected_s):
            return False, (f"rejected: file is {probed or 0:.0f}s but this track "
                           f"is {expected_s or 0:.0f}s on Spotify — wrong version")
        ok, msg = _swap(cache, track_id, audio_path, spectrogram_dir, expected_s, {
            "source": "upload", "matcher_version": "manual-upload",
            "youtube_title": _UPLOAD_TITLE, "audio_format": fmt,
            "youtube_duration_s": probed})
        if ok and keep_dir is not None:
            # V2: keep the ONLY copy (see the docstring) — copy, don't move, so
            # the finally-cleanup below stays a single unconditional rule.
            try:
                kept = owner_audio_path(keep_dir, track_id, fmt)
                kept.parent.mkdir(parents=True, exist_ok=True)
                for other in (keep_dir / f"{Path(track_id).name}.{f}"
                              for f in ("mp3", "wav", "flac", "m4a")):
                    if other != kept:
                        other.unlink(missing_ok=True)   # a re-upload replaces
                kept.write_bytes(audio_path.read_bytes())
            except OSError as exc:
                logger.warning("could not retain upload for %s: %s", track_id, exc)
        return ok, msg
    except Exception as exc:  # noqa: BLE001 — a repair must never 500 the app
        logger.warning("repair_from_upload failed for %s: %s", track_id, exc)
        return False, f"repair failed: {exc}"
    finally:
        if audio_path is not None:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass
