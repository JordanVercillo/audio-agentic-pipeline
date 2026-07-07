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
from pathlib import Path
from typing import Callable, Optional

from ..dsp.audio_loader import load_audio
from ..dsp.feature_extractor import extract_features
from .cache import FeatureCache

logger = logging.getLogger(__name__)

DSP_VERSION = "77dim-v1"

# (track_id, track_name, artist_names, dest_dir) -> path to the audio file, or None.
AcquireFn = Callable[[str, str, str, Path], Optional[Path]]


def default_acquire(track_id: str, name: str, artist: str, dest_dir: Path) -> Optional[Path]:
    """Resolve + download the track's audio via the existing yt-dlp downloader."""
    from ..ingestion.audio_downloader import (
        DownloadConfig,
        download_track_audio,
        resolve_youtube_url,
    )
    url = resolve_youtube_url(name, artist or "")
    if not url:
        return None
    return download_track_audio(url, track_id, DownloadConfig(output_dir=Path(dest_dir)))


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


def extract_one(cache: FeatureCache, track_id: str, *, audio_dir: Path,
                spectrogram_dir: Path, acquire: AcquireFn = default_acquire) -> bool:
    """Acquire → DSP → spectrogram → cache one track. Returns True on success.

    Never raises — any failure marks the job failed so the worker keeps draining.
    """
    meta = cache.get_meta(track_id)
    if not meta or not meta.get("track_name"):
        cache.fail(track_id, "no track metadata for the audio search")
        return False

    audio_path: Optional[Path] = None
    try:
        audio_path = acquire(track_id, meta["track_name"], meta.get("artist_names") or "",
                             Path(audio_dir))
        if audio_path is None or not Path(audio_path).exists():
            cache.fail(track_id, "audio acquisition failed")
            return False

        signal = load_audio(audio_path)
        features = extract_features(signal).to_summary_dict()
        spec_uri = make_mel_spectrogram(signal, Path(spectrogram_dir) / f"{track_id}.png")

        cache.upsert(track_id, features, spectrogram_uri=str(spec_uri),
                     source="youtube", dsp_version=DSP_VERSION)
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
          max_jobs: Optional[int] = None, acquire: AcquireFn = default_acquire) -> dict:
    """Claim + extract queued jobs until the queue is empty (or max_jobs reached)."""
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
    return {"done": done, "failed": failed}
