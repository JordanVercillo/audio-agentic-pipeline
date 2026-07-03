"""
audio_downloader.py — Audio Acquisition Layer (Phase 1)
=========================================================
Automatically finds and downloads MP3 audio for every ``spotify_track_id``
using ``yt_dlp``, bridging the gap between Spotify metadata (already ingested
via ``fetchers.py``) and the real audio files required by the DSP pipeline.

Architecture
------------
::

    Spotify Metadata (fetchers.py)
          │
          │   spotify_track_id + track_name + artist_names
          ▼
    ┌─────────────────────────────┐
    │  resolve_youtube_url()      │  YouTube search (yt_dlp, no API key)
    └─────────────┬───────────────┘
                  │   youtube URL
                  ▼
    ┌─────────────────────────────┐
    │  download_track_audio()     │  yt_dlp → FFmpeg → MP3 192 kbps
    └─────────────┬───────────────┘
                  │   data/raw_audio/{spotify_track_id}.mp3
                  ▼
    ┌─────────────────────────────┐
    │  src/dsp/collection_extractor.py  (Phase 2)
    └─────────────────────────────┘

Bridge Key
----------
``spotify_track_id`` is the universal join key across ALL pipeline layers.
Audio files MUST be named ``{spotify_track_id}.mp3`` — the filename stem
IS the bridge key; no lookup table is required.

Idempotency
-----------
``should_skip_download()`` checks two conditions before every download:

1. ``data/raw_audio/{spotify_track_id}.mp3`` already exists with size > 0.
2. ``data/warehouse/cleansed/cleansed_features.parquet`` already contains
   features for this ``spotify_track_id``.

Either condition is sufficient to skip the download.

Security
--------
* ``yt-dlp >= 2026.2.21`` (CVE patches — see requirements.txt).
* No hardcoded URLs, credentials, or API keys.
* All configuration via the ``DownloadConfig`` dataclass.

References
----------
* CLAUDE_INSTRUCTIONS.md — ADR-004, ADR-005, ADR-006
* src/ingestion/guardrails.py — rate-limiting patterns
* src/dsp/collection_extractor.py — consumes ``data/raw_audio/``
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATH CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_AUDIO_DIR = _PROJECT_ROOT / "data" / "raw_audio"
_CLEANSED_FEATURES_PATH = (
    _PROJECT_ROOT / "data" / "warehouse" / "cleansed" / "cleansed_features.parquet"
)

# Score adjustments applied when ranking YouTube search results.
_POSITIVE_KEYWORDS = frozenset({"official audio", "lyrics", "official video"})
_NEGATIVE_KEYWORDS = frozenset({"live", "cover", "karaoke", "remix", "instrumental"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION DATACLASS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class DownloadConfig:
    """Runtime configuration for the audio download pipeline.

    All timing parameters are in seconds. Randomised delays are used to
    avoid triggering YouTube's automated rate-detection systems.

    Attributes:
        output_dir:   Directory where ``{spotify_track_id}.mp3`` files are saved.
        min_delay:    Minimum seconds to wait between consecutive downloads.
        max_delay:    Maximum seconds to wait between consecutive downloads.
        max_retries:  Number of times to retry a failed download before giving up.
        backoff_base: Exponential-backoff multiplier applied on each retry.
        error_delay:  Base delay (seconds) applied after receiving HTTP 429 responses.
    """

    output_dir: Path = field(default_factory=lambda: RAW_AUDIO_DIR)
    min_delay: float = 5.0
    max_delay: float = 30.0
    max_retries: int = 3
    backoff_base: float = 2.0
    error_delay: float = 60.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 1.1 — YOUTUBE SEARCH RESOLVER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def resolve_youtube_url(
    track_name: str,
    artist_name: str,
    prefer_official: bool = True,
) -> Optional[str]:
    """Find the best YouTube URL for a track using yt_dlp's flat search.

    Queries YouTube for the top 5 results using ``ytsearch5:``, then ranks
    candidates by title keywords.  Titles containing "Official Audio" or
    "Lyrics" are preferred; titles containing "Live" or "Cover" are
    deprioritised.  No YouTube Data API key is required.

    Args:
        track_name:      The name of the track (e.g., ``"Bohemian Rhapsody"``).
        artist_name:     The primary artist name (e.g., ``"Queen"``).
        prefer_official: If ``True``, append "official audio" to the query string
                         to bias YouTube's ranking toward studio recordings.

    Returns:
        A ``str`` YouTube watch URL (``https://www.youtube.com/watch?v=...``)
        for the best matching video, or ``None`` if no suitable result is found.
    """
    try:
        import yt_dlp  # local import — optional dependency
    except ImportError:
        logger.error(
            "yt_dlp is not installed. Add 'yt-dlp>=2026.2.21' to requirements.txt."
        )
        return None

    suffix = " official audio" if prefer_official else ""
    query = f"{artist_name} {track_name}{suffix}"
    search_term = f"ytsearch5:{query}"

    logger.debug("YouTube search query: %r", query)

    ydl_opts: dict = {
        "extract_flat": True,
        "default_search": "ytsearch5",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_term, download=False)
    except yt_dlp.utils.DownloadError as exc:
        logger.warning("yt_dlp search failed for %r: %s", query, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error during YouTube search for %r: %s", query, exc)
        return None

    entries = (info or {}).get("entries") or []
    if not entries:
        logger.debug("No YouTube results for query: %r", query)
        return None

    best_url: Optional[str] = None
    best_score: int = -1_000

    for entry in entries:
        if not entry:
            continue
        title_lower = (entry.get("title") or "").lower()
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            continue

        score = 0
        for kw in _POSITIVE_KEYWORDS:
            if kw in title_lower:
                score += 10
        for kw in _NEGATIVE_KEYWORDS:
            if kw in title_lower:
                score -= 15

        logger.debug("Candidate %r — score=%d — url=%s", entry.get("title"), score, url)

        if score > best_score:
            best_score = score
            best_url = url

    if best_url:
        logger.debug("Selected result: %s (score=%d)", best_url, best_score)
    else:
        logger.debug("No suitable YouTube result for %r", query)

    return best_url


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 1.2 — MP3 DOWNLOADER WITH BRIDGE KEY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def download_track_audio(
    youtube_url: str,
    spotify_track_id: str,
    config: Optional[DownloadConfig] = None,
) -> Optional[Path]:
    """Download a YouTube video as a 192 kbps MP3, named by bridge key.

    The output file is always named ``{spotify_track_id}.mp3`` so that the
    filename stem is the bridge key and no separate lookup table is needed.

    Args:
        youtube_url:      The YouTube watch URL obtained from
                          :func:`resolve_youtube_url`.
        spotify_track_id: The Spotify track ID used as the filename stem.
        config:           Optional :class:`DownloadConfig`.  Defaults are used
                          when ``None``.

    Returns:
        A :class:`~pathlib.Path` pointing to the downloaded ``.mp3`` file, or
        ``None`` if the download fails.
    """
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt_dlp is not installed. Add 'yt-dlp>=2026.2.21' to requirements.txt.")
        return None

    if config is None:
        config = DownloadConfig()

    output_dir: Path = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use %(ext)s so yt_dlp writes the raw download before FFmpeg renames it.
    outtmpl = str(output_dir / f"{spotify_track_id}.%(ext)s")
    expected_path = output_dir / f"{spotify_track_id}.mp3"

    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    logger.info(
        "Downloading audio: spotify_track_id=%s url=%s", spotify_track_id, youtube_url
    )

    for attempt in range(1, config.max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])

            if expected_path.exists() and expected_path.stat().st_size > 0:
                logger.info(
                    "Download complete: %s (%.1f KB)",
                    expected_path.name,
                    expected_path.stat().st_size / 1024,
                )
                return expected_path

            logger.warning(
                "yt_dlp finished but expected file not found: %s", expected_path
            )
            return None

        except yt_dlp.utils.DownloadError as exc:
            error_msg = str(exc)

            # HTTP 429 / rate-limit handling
            if "429" in error_msg or "Too Many Requests" in error_msg:
                wait = config.error_delay * (config.backoff_base ** (attempt - 1))
                logger.warning(
                    "HTTP 429 for %s (attempt %d/%d) — backing off %.0fs",
                    spotify_track_id,
                    attempt,
                    config.max_retries,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "yt_dlp download error for %s (attempt %d/%d): %s",
                    spotify_track_id,
                    attempt,
                    config.max_retries,
                    exc,
                )
                if attempt < config.max_retries:
                    backoff = config.backoff_base ** attempt
                    logger.debug("Retrying in %.1fs…", backoff)
                    time.sleep(backoff)

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error downloading %s (attempt %d/%d): %s",
                spotify_track_id,
                attempt,
                config.max_retries,
                exc,
            )
            if attempt < config.max_retries:
                backoff = config.backoff_base ** attempt
                time.sleep(backoff)

    logger.error(
        "All %d download attempts failed for %s", config.max_retries, spotify_track_id
    )
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 1.4 — IDEMPOTENT SKIP LOGIC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def should_skip_download(
    spotify_track_id: str,
    config: Optional[DownloadConfig] = None,
) -> bool:
    """Return ``True`` if this track should be skipped during a batch run.

    Two conditions trigger a skip (either is sufficient):

    1. ``data/raw_audio/{spotify_track_id}.mp3`` already exists with
       a non-zero file size.
    2. ``data/warehouse/cleansed/cleansed_features.parquet`` already
       contains a row whose ``spotify_track_id`` column matches.

    Args:
        spotify_track_id: The Spotify track ID to check.
        config:           Optional :class:`DownloadConfig` (used to resolve
                          the output directory).  Defaults are used when ``None``.

    Returns:
        ``True`` if the download can be safely skipped, ``False`` otherwise.
    """
    if config is None:
        config = DownloadConfig()

    output_dir = Path(config.output_dir)
    mp3_path = output_dir / f"{spotify_track_id}.mp3"

    # Check 1 — MP3 file already on disk.
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        logger.info(
            "SKIP [file exists]: %s (%.1f KB)",
            mp3_path.name,
            mp3_path.stat().st_size / 1024,
        )
        return True

    # Check 2 — Features already in the cleansed Parquet warehouse layer.
    if _CLEANSED_FEATURES_PATH.exists():
        try:
            df_features = pd.read_parquet(
                _CLEANSED_FEATURES_PATH,
                engine="pyarrow",
                columns=["spotify_track_id"],
            )
            if spotify_track_id in df_features["spotify_track_id"].values:
                logger.info(
                    "SKIP [features in warehouse]: spotify_track_id=%s", spotify_track_id
                )
                return True
        except Exception as exc:  # noqa: BLE001
            # Corrupt or unreadable Parquet — do not skip; let the download proceed.
            logger.warning(
                "Could not read cleansed_features.parquet (will not skip): %s", exc
            )

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 1.5 — BATCH ORCHESTRATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def download_audio_for_tracks(
    tracks_df: pd.DataFrame,
    config: Optional[DownloadConfig] = None,
) -> pd.DataFrame:
    """Download MP3 audio for every track in *tracks_df*.

    Processes each track in order, applying idempotency checks and
    inter-download rate-limiting delays.  The returned summary DataFrame
    has one row per input track, regardless of whether the download
    succeeded, was skipped, or failed.

    Args:
        tracks_df: A :class:`~pandas.DataFrame` with at minimum the columns
                   ``spotify_track_id``, ``track_name``, and ``artist_names``
                   (as produced by :func:`~src.ingestion.fetchers.fetch_all_top_items`).
        config:    Optional :class:`DownloadConfig`.  Defaults are used when
                   ``None``.

    Returns:
        A :class:`~pandas.DataFrame` with columns:

        * ``spotify_track_id`` — bridge key (``str``)
        * ``local_audio_path`` — absolute path to the MP3, or ``""`` (``str``)
        * ``download_status`` — one of ``"success"``, ``"skipped"``,
          ``"failed"``, or ``"no_match"``
        * ``error_message`` — human-readable reason on failure, else ``""``

    Note:
        Calling this function twice with the same *tracks_df* is fully
        idempotent: the second call will skip every track and return
        ``download_status == "skipped"`` for all rows.
    """
    if tracks_df.empty:
        logger.info("download_audio_for_tracks: empty DataFrame — nothing to do.")
        return pd.DataFrame(
            columns=["spotify_track_id", "local_audio_path", "download_status", "error_message"]
        )

    if config is None:
        config = DownloadConfig()

    required_cols = {"spotify_track_id", "track_name", "artist_names"}
    missing = required_cols - set(tracks_df.columns)
    if missing:
        raise ValueError(
            f"tracks_df is missing required columns: {missing}. "
            "Expected output from fetch_all_top_items()."
        )

    results: list[dict] = []
    n_success = 0
    n_skipped = 0
    n_failed = 0
    n_no_match = 0

    total = len(tracks_df)
    logger.info("Starting batch audio download: %d tracks.", total)

    for idx, row in tracks_df.iterrows():
        track_id: str = str(row["spotify_track_id"])
        track_name: str = str(row["track_name"])
        # artist_names may be a comma-separated string (e.g., "Queen, David Bowie")
        artist_names: str = str(row["artist_names"])
        primary_artist = artist_names.split(",")[0].strip()

        record: dict = {
            "spotify_track_id": track_id,
            "local_audio_path": "",
            "download_status": "",
            "error_message": "",
        }

        # ── Idempotency check ──────────────────────────────────────────
        if should_skip_download(track_id, config=config):
            record["download_status"] = "skipped"
            mp3_path = Path(config.output_dir) / f"{track_id}.mp3"
            if mp3_path.exists():
                record["local_audio_path"] = str(mp3_path)
            results.append(record)
            n_skipped += 1
            continue

        # ── YouTube search ─────────────────────────────────────────────
        youtube_url = resolve_youtube_url(track_name, primary_artist)
        if youtube_url is None:
            logger.warning(
                "No YouTube match for %r by %r (spotify_track_id=%s)",
                track_name,
                primary_artist,
                track_id,
            )
            record["download_status"] = "no_match"
            record["error_message"] = f"No YouTube result for '{primary_artist} {track_name}'"
            results.append(record)
            n_no_match += 1
            continue

        # ── Download ───────────────────────────────────────────────────
        mp3_path = download_track_audio(youtube_url, track_id, config=config)
        if mp3_path is not None:
            record["download_status"] = "success"
            record["local_audio_path"] = str(mp3_path)
            n_success += 1
        else:
            record["download_status"] = "failed"
            record["error_message"] = f"yt_dlp failed after {config.max_retries} attempts"
            n_failed += 1

        results.append(record)

        # ── Rate-limiting delay ────────────────────────────────────────
        # Applied after every attempted download (success or failure),
        # but NOT after skips to keep batch runs fast.
        if idx < total - 1:  # no delay after the last track
            delay = random.uniform(config.min_delay, config.max_delay)
            logger.debug("Rate-limit delay: %.1fs before next download.", delay)
            time.sleep(delay)

    # ── Batch summary ──────────────────────────────────────────────────
    logger.info(
        "Batch complete — Downloaded: %d | Skipped: %d | No match: %d | Failed: %d",
        n_success,
        n_skipped,
        n_no_match,
        n_failed,
    )

    return pd.DataFrame(results)
