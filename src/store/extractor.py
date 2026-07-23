"""
extractor.py — the extraction worker (APP_SPEC Epic A slice 2).

Drains the FeatureCache queue: claim a queued track → acquire its audio
(yt-dlp) → run the local DSP (the 77-dim librosa pipeline) + render a
mel-spectrogram → `cache.upsert`. **Analyze once, ever** (D-11).

Ground rules honored:
    - Reuses the existing pipeline verbatim: `audio_loader.load_audio` +
      `feature_extractor.extract_features` (the frozen 77-dim contract).
    - **Audio is transient** — the derived features + spectrogram are the durable
      artifacts; the downloaded file is deleted after extraction (D-15).
    - The `acquire` step is injectable, so tests drive the whole path on
      synthetic audio with no YouTube and no network (ground rule).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..dsp.audio_loader import load_audio
from ..dsp.feature_extractor import extract_features
from .cache import FeatureCache

logger = logging.getLogger(__name__)

DSP_VERSION = "77dim-v1"
# The download pipeline always produces a 192 kbps MP3 (audio_downloader's
# ydl opts) — recorded on the provenance row as the acquired encoding (D-51).
_AUDIO_FORMAT, _AUDIO_BITRATE_KBPS = "mp3", 192

# The id becomes a FILENAME ({id}.mp3 / {id}.png) — this is the worker-side
# twin of the webapp's path-traversal strip (defense in depth). The threat is
# the CHARSET (separators/dots), not length: base62-only makes traversal
# unspellable; the cap just bounds the filename. (Real Spotify ids: 22 base62.)
_TRACK_ID_RE = re.compile(r"[0-9A-Za-z]{1,64}")

# (track_id, track_name, artist_names, dest_dir, duration_s) ->
#   (path to the audio file or None, match record or None).
# The match record is resolve_youtube_match's dict — its `confidence` is
# recorded on the extraction (O2, D-22); duration_s enables the duration term.
AcquireFn = Callable[[str, str, str, Path, Optional[float]],
                     tuple[Optional[Path], Optional[dict]]]


def default_acquire(track_id: str, name: str, artist: str, dest_dir: Path,
                    duration_s: Optional[float] = None,
                    ) -> tuple[Optional[Path], Optional[dict]]:
    """Resolve + download the track's audio via the yt-dlp downloader (O2:
    duration-aware match, confidence returned for recording)."""
    from ..ingestion.audio_downloader import (
        DownloadConfig,
        download_track_audio,
        resolve_youtube_match,
    )
    match = resolve_youtube_match(name, artist or "", duration_s=duration_s)
    if not match:
        return None, None
    path = download_track_audio(match["url"], track_id,
                                DownloadConfig(output_dir=Path(dest_dir)))
    return path, match


def make_mel_spectrogram(signal, out_path: Path) -> Path:
    """Render a mel-spectrogram PNG from an AudioSignal (a derived artifact — D-15)."""
    import librosa
    import librosa.display
    import matplotlib
    matplotlib.use("Agg")  # headless — safe in workers/CI
    import matplotlib.pyplot as plt
    import numpy as np

    mel = librosa.feature.melspectrogram(y=signal.waveform, sr=signal.sr, n_mels=128)
    mel_db = librosa.power_to_db(mel, ref=np.max)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.0, 2.2), dpi=110)
    librosa.display.specshow(mel_db, sr=signal.sr, x_axis="time", y_axis="mel",
                             ax=ax, cmap="magma")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return out_path


def another_worker_alive(heartbeat: Optional[dict], my_pid: int,
                         now: Optional[datetime] = None) -> bool:
    """True when a DIFFERENT worker looks alive — the caller should refuse to
    start (two workers double-extract tracks and double-write spectrograms).

    "Alive" = its heartbeat is fresher than 3 poll intervals (min 300 s — the
    same staleness rule app-verify's WORKER_DOWN uses). Stale/absent = a dead
    worker's leftovers: safe to start. A future-dated beat (clock skew) counts
    as alive. Same-pid beats are ours (a restart), never a conflict. The
    simultaneous-cold-start race is accepted: the lock targets the real case —
    a human starting a second worker while one has been beating for minutes.
    """
    if not heartbeat or heartbeat.get("beat_at") is None:
        return False
    if heartbeat.get("pid") == my_pid:
        return False
    stale_after = max(3 * (heartbeat.get("interval_seconds") or 30), 300)
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    age = (now - heartbeat["beat_at"]).total_seconds()
    return age <= stale_after


def _record_provenance(cache: FeatureCache, track_id: str,
                       match: Optional[dict]) -> int:
    """Persist one D-51 acquisition event from the matcher's record. Everything
    here was already returned by resolve_youtube_match — nothing is re-fetched.
    Returns the row id (-1 on a swallowed failure) — the Q3 runner checks it:
    provenance is its resume marker, so a silent miss must surface (red-team #5)."""
    m = match or {}
    return cache.remember_provenance(
        spotify_track_id=track_id,
        youtube_url=m.get("url"), youtube_video_id=m.get("youtube_video_id"),
        youtube_title=m.get("title"), channel=m.get("channel"),
        youtube_duration_s=m.get("youtube_duration_s"),
        upload_date=m.get("upload_date"), query=m.get("query"),
        match_score=m.get("score"), match_confidence=m.get("confidence"),
        duration_delta_s=m.get("duration_delta_s"),
        matcher_version=m.get("matcher_version"),
        candidate_count=m.get("candidate_count"),
        audio_format=_AUDIO_FORMAT, audio_bitrate_kbps=_AUDIO_BITRATE_KBPS,
        dsp_version=DSP_VERSION)


def extract_one(cache: FeatureCache, track_id: str, *, audio_dir: Path,
                spectrogram_dir: Path, acquire: AcquireFn = default_acquire) -> bool:
    """Acquire → DSP → spectrogram → cache one track. Returns True on success.

    Never raises — any failure marks the job failed so the worker keeps draining.
    """
    if not _TRACK_ID_RE.fullmatch(track_id or ""):
        cache.fail(track_id, "invalid track id shape")
        return False

    meta = cache.get_meta(track_id)
    if not meta or not meta.get("track_name"):
        cache.fail(track_id, "no track metadata for the audio search")
        return False

    # O1 (D-28): a near-duplicate was analyzed first (the both-new race) → reuse
    # it, skip the redundant download+DSP. Resolve as a duplicate (flag + job
    # done); nothing re-fetched, bridge key untouched. find_cached_twin is
    # best-effort and never raises.
    twin = cache.find_cached_twin(track_id)
    if twin is not None:
        cache.resolve_duplicate(track_id, twin)
        logger.info("deduped %s: same recording as cached %s (no download)", track_id, twin)
        return True

    audio_path: Optional[Path] = None
    try:
        dur_ms = meta.get("duration_ms")
        audio_path, match = acquire(track_id, meta["track_name"],
                                    meta.get("artist_names") or "", Path(audio_dir),
                                    (dur_ms / 1000.0) if dur_ms else None)
        if audio_path is None or not Path(audio_path).exists():
            cache.fail(track_id, "audio acquisition failed")
            return False

        signal = load_audio(audio_path)
        tf = extract_features(signal)
        features = tf.to_summary_dict()
        spec_uri = make_mel_spectrogram(signal, Path(spectrogram_dir) / f"{track_id}.png")

        cache.upsert(track_id, features, spectrogram_uri=str(spec_uri),
                     source="youtube", dsp_version=DSP_VERSION,
                     loudness_curve=tf.loudness_curve_points(),
                     time_signature=tf.time_signature,
                     beat_times=tf.beat_times_list(),
                     sections=tf.sections_list(),
                     match_confidence=(match or {}).get("confidence"))
        # Epic Q (D-51): record where this audio came from + the match quality,
        # from what the matcher already returned (zero new fetches). Best-effort
        # — a provenance write never fails the extraction it describes.
        _record_provenance(cache, track_id, match)
        return True
    except Exception as exc:  # noqa: BLE001 — a bad track must never crash the worker
        logger.warning("extraction failed for %s: %s", track_id, exc)
        cache.fail(track_id, str(exc))
        return False
    finally:
        # D-15: audio is transient — the features + spectrogram are the artifacts.
        if audio_path is not None:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass


def drain(cache: FeatureCache, *, audio_dir: Path, spectrogram_dir: Path,
          max_jobs: Optional[int] = None, acquire: AcquireFn = default_acquire,
          on_progress: Optional[Callable[[], None]] = None) -> dict:
    """Claim + extract queued jobs until the queue is empty (or max_jobs reached).

    `on_progress` fires after every job — a long queue must not starve the
    caller's liveness heartbeat (one visitor can queue ~an hour of work).
    """
    done = failed = 0
    while max_jobs is None or (done + failed) < max_jobs:
        track_id = cache.claim_next()
        if track_id is None:
            break
        if extract_one(cache, track_id, audio_dir=audio_dir,
                       spectrogram_dir=spectrogram_dir, acquire=acquire):
            done += 1
        else:
            failed += 1
        if on_progress is not None:
            on_progress()
    return {"done": done, "failed": failed}
