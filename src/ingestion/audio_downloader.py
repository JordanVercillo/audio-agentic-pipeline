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
import os
import random
import subprocess
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

# O2 (D-22) duration term — the strongest wrong-version signal we have: a live
# cut / extended mix is usually tens of seconds off the studio length, while
# official uploads sit within a few seconds of Spotify's duration_ms.
# HEURISTIC-V1 WEIGHTS — SIGNED OFF 2026-07-22 (context-only, NO rejection
# threshold). The corpus evidence is now in (508 tracks scored: median 0.85,
# strong right-skew). The low tail is NOT wrong-song matches: all 26 near-zero
# tracks spot-check as legit electronic/DJ imports — "VIP"/"Mixed"/"Remix"/
# "Edit" versions whose non-studio duration + negative-keyword hits drive the
# score down, while the audio is the right recording (they form the Punchy·
# Smooth cluster). A blanket threshold at 0.5 would discard 63 real tracks and
# gut the electronic genre. So match_confidence stays LOGGING/CONTEXT only —
# never a gate. A future threshold must FIRST make the heuristic remix-aware
# (recognize VIP/Mixed/Edit, relax the duration term) or it is biased against
# electronic music.
_DURATION_BANDS = (  # (max |delta| seconds, score adjustment)
    (3.0, 25),
    (10.0, 12),
    (25.0, 0),
    (45.0, -10),
)
_DURATION_FAR_PENALTY = -30   # |delta| beyond the last band
# confidence = a monotone [0,1] map of the raw score for logging/analysis;
# 0.46 ≈ "nothing known either way". Display/analysis heuristic, never a gate.
_CONF_OFFSET, _CONF_RANGE = 30.0, 65.0
# Stamped on each provenance row (Epic Q / D-51) so a re-tuned matcher's rows
# are distinguishable — and it is the version the O2 sign-off (S2) applies to.
MATCHER_VERSION = "heuristic-v1"

# How many search results to score. Was 5, when only the winner was ever used.
# The QA2 gate filters candidates instead of judging one, so a deeper pool is
# free precision: same single flat-search request, more chances that an
# ADMISSIBLE recording is in it. Measured on the needs-source queue — real
# matches sat as far down as position 6.
_SEARCH_DEPTH = 10


def _can_encode_mp3(exe: str) -> bool:
    """Does THIS ffmpeg build actually have the MP3 encoder? Asking the binary
    is the only reliable test — the name tells you nothing."""
    try:
        out = subprocess.run([exe, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20, check=False)
        return "libmp3lame" in (out.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _mp3_capable_candidates() -> list[str]:
    """Every ffmpeg worth trying, in priority order: the explicit override,
    then EVERY entry on PATH (not just the first — the first is exactly what
    was broken), then the usual full-build install locations."""
    candidates: list[str] = []
    override = os.environ.get("FFMPEG_LOCATION")
    if override:
        p = Path(override)
        candidates.append(str(p if p.suffix else p / "ffmpeg.exe"))

    exe_names = ("ffmpeg.exe", "ffmpeg")
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        if not entry:
            continue
        for name in exe_names:
            candidates.append(str(Path(entry) / name))

    home = Path.home()
    try:  # WinGet's Gyan full build — the one that actually has libmp3lame
        candidates += [str(p) for p in sorted(
            (home / "AppData/Local/Microsoft/WinGet/Packages").glob(
                "Gyan.FFmpeg*/**/bin/ffmpeg.exe"))]
    except OSError:
        pass
    candidates += [r"C:\ffmpeg\bin\ffmpeg.exe",
                   r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"]

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        key = c.lower()
        if key not in seen and Path(c).exists():
            seen.add(key)
            out.append(c)
    return out


def ffmpeg_location() -> Optional[str]:
    """Directory of an ffmpeg that can actually encode MP3, or None if none
    can be found (then yt-dlp is on its own).

    Why this exists (live bug, 2026-07-23): a repair download completed and
    then failed postprocessing with "Encoder not found". The webapp's PATH put
    **Anaconda's** ffmpeg first — a build with NO libmp3lame — while a shell
    found the WinGet full build, so acquisition was silently
    environment-dependent. The first fix only DETECTED the bad binary and
    returned None, which handed yt-dlp straight back to that same bad ffmpeg;
    detecting a problem is not solving it. So now we keep looking: every
    candidate is asked whether it can encode MP3, and the first that CAN wins.
    FFMPEG_LOCATION still overrides for ops."""
    for exe in _mp3_capable_candidates():
        if _can_encode_mp3(exe):
            return str(Path(exe).parent)
    logger.error("no ffmpeg with libmp3lame found — audio acquisition will "
                 "fail at conversion; install a full build or set FFMPEG_LOCATION")
    return None


def score_candidate(title: str, duration_s: Optional[float],
                    target_duration_s: Optional[float]) -> int:
    """Score one search candidate: title keywords + the duration-closeness term.
    Pure — unit-tested without network (ground rule #5)."""
    title_lower = (title or "").lower()
    score = 0
    for kw in _POSITIVE_KEYWORDS:
        if kw in title_lower:
            score += 10
    for kw in _NEGATIVE_KEYWORDS:
        if kw in title_lower:
            score -= 15
    if duration_s is not None and target_duration_s is not None:
        delta = abs(float(duration_s) - float(target_duration_s))
        for band_max, adj in _DURATION_BANDS:
            if delta <= band_max:
                score += adj
                break
        else:
            score += _DURATION_FAR_PENALTY
    return score


def score_all_candidates(entries: list,
                         target_duration_s: Optional[float]) -> list[dict]:
    """Score EVERY flat-search entry → a list of match records, search order kept.

    Each record is {url, title, score, confidence, duration_delta_s} plus the
    Epic-Q provenance fields the flat entry already carries but we used to
    discard (`youtube_video_id`, `youtube_duration_s`, `channel`,
    `candidate_count`) — `confidence` is the [0,1] heuristic map of the score;
    `duration_delta_s` is None when either duration is unknown.

    Why the whole list and not just the winner (QA2): ranking first and judging
    the winner afterwards throws away a usable candidate sitting at position 2
    of the very same search. `match_gate.select_confident` filters this list
    and then ranks the survivors. Pure."""
    scored: list[dict] = []
    for entry in entries or []:
        if not entry:
            continue
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            continue
        title = entry.get("title") or ""
        dur = entry.get("duration")
        score = score_candidate(title, dur, target_duration_s)
        delta = (abs(float(dur) - float(target_duration_s))
                 if dur is not None and target_duration_s is not None else None)
        scored.append({
            "url": url, "title": title, "score": score,
            "confidence": max(0.0, min(1.0, (score + _CONF_OFFSET) / _CONF_RANGE)),
            "duration_delta_s": delta,
            # Epic Q (D-51): captured, not fetched — already in the entry.
            "youtube_video_id": entry.get("id"),
            "youtube_duration_s": float(dur) if dur is not None else None,
            "channel": entry.get("channel") or entry.get("uploader")})
    for rec in scored:
        rec["candidate_count"] = len(scored)
    return scored


def pick_best_candidate(entries: list, target_duration_s: Optional[float]) -> Optional[dict]:
    """Rank flat-search entries → the highest-scoring match record, or None.

    Selection ONLY — never rejection (see the heuristic-v1 note at the
    weights). Admissibility is `match_gate`'s job. Ties keep the earlier
    (higher-ranked by YouTube) entry. Pure."""
    best: Optional[dict] = None
    for rec in score_all_candidates(entries, target_duration_s):
        if best is None or rec["score"] > best["score"]:
            best = rec
    return best


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


def resolve_youtube_match(
    track_name: str,
    artist_name: str,
    duration_s: Optional[float] = None,
    prefer_official: bool = True,
) -> Optional[dict]:
    """Find the best-SCORING YouTube match for a track (O2).

    Scores each search candidate by title keywords AND duration closeness
    against Spotify's ``duration_ms`` (the strongest wrong-version signal —
    live cuts and extended mixes are tens of seconds off), then returns the
    best as a match record. No YouTube Data API key is required.

    Selection only. This function has no opinion on whether the winner is
    ADMISSIBLE — acquisition paths go through ``match_gate`` for that, because
    "best of five wrong answers" is how DJ sets and wrong songs entered the
    corpus. Prefer ``resolve_youtube_candidates`` + ``select_confident``.

    Args:
        track_name:      The name of the track (e.g., ``"Bohemian Rhapsody"``).
        artist_name:     The primary artist name (e.g., ``"Queen"``).
        duration_s:      Spotify's track duration in SECONDS, when known —
                         enables the duration term; scoring degrades gracefully
                         without it.
        prefer_official: If ``True``, append "official audio" to the query string
                         to bias YouTube's ranking toward studio recordings.

    Returns:
        ``{url, title, score, confidence, duration_delta_s}`` for the best
        candidate, or ``None`` if no result was found. The match is ALWAYS the
        best available — never rejected on a threshold (selection + recording
        only; see the heuristic-v1 note at the weights).
    """
    candidates = resolve_youtube_candidates(track_name, artist_name,
                                            duration_s=duration_s,
                                            prefer_official=prefer_official)
    if not candidates:
        return None
    # These are already scored records — re-running the scorer over them would
    # read `duration` off a dict that now spells it `youtube_duration_s` and
    # silently drop the duration term. Take the max directly; ties keep the
    # earlier (higher-ranked) entry, as before.
    best = candidates[0]
    for rec in candidates[1:]:
        if rec["score"] > best["score"]:
            best = rec
    # O2 acceptance: the match decision is always visible in the worker log.
    delta = best["duration_delta_s"]
    logger.info(
        "match %r: score=%d conf=%.2f dur_delta=%s title=%r",
        best.get("query"), best["score"], best["confidence"],
        f"{delta:.1f}s" if delta is not None else "unknown", best["title"],
    )
    return best


def resolve_youtube_candidates(
    track_name: str,
    artist_name: str,
    duration_s: Optional[float] = None,
    prefer_official: bool = True,
    depth: int = _SEARCH_DEPTH,
) -> list[dict]:
    """Every scored candidate for this track, search order kept (QA2).

    One search, two policies: `resolve_youtube_match` takes the top-scoring
    record, `match_gate.select_confident` takes the best ADMISSIBLE one. The
    gate needs the whole list because the top-scoring candidate is regularly
    inadmissible while a usable one sits below it.

    Returns ``[]`` on any search failure — callers treat empty as "no match",
    never as "no opinion". Each record carries the Epic-Q `query` +
    `matcher_version` provenance fields."""
    try:
        import yt_dlp  # local import — optional dependency
    except ImportError:
        logger.error(
            "yt_dlp is not installed. Add 'yt-dlp>=2026.2.21' to requirements.txt."
        )
        return []

    suffix = " official audio" if prefer_official else ""
    query = f"{artist_name} {track_name}{suffix}"
    search_term = f"ytsearch{int(depth)}:{query}"

    logger.debug("YouTube search query: %r", query)

    ydl_opts: dict = {
        "extract_flat": True,
        "default_search": search_term.split(":")[0],
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_term, download=False)
    except yt_dlp.utils.DownloadError as exc:
        logger.warning("yt_dlp search failed for %r: %s", query, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error during YouTube search for %r: %s", query, exc)
        return []

    entries = (info or {}).get("entries") or []
    if not entries:
        logger.debug("No YouTube results for query: %r", query)
        return []

    candidates = score_all_candidates(entries, duration_s)
    for rec in candidates:
        # Epic Q (D-51): the resolve layer knows the query + which matcher scored it.
        rec["query"] = query
        rec["matcher_version"] = MATCHER_VERSION
    return candidates


def resolve_youtube_url(
    track_name: str,
    artist_name: str,
    prefer_official: bool = True,
) -> Optional[str]:
    """Back-compat wrapper: the best match's URL only (no duration term)."""
    match = resolve_youtube_match(track_name, artist_name,
                                  prefer_official=prefer_official)
    return match["url"] if match else None


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
    # PIN the ffmpeg build (live bug, 2026-07-23): the download succeeded but
    # postprocessing died with "Encoder not found" — yt-dlp resolved a
    # DIFFERENT ffmpeg than the shell's (no libmp3lame) because it inherits
    # whatever PATH the launching process had. A critical binary must not
    # depend on ambient PATH ordering, so resolve it once, explicitly.
    ffmpeg_dir = ffmpeg_location()
    if ffmpeg_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir

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
