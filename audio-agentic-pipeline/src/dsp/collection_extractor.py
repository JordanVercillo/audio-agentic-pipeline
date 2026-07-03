"""
collection_extractor.py — Real Audio Feature Extraction Pipeline (Phase 2)
===========================================================================
Runs the existing 77-dimensional DSP pipeline on real downloaded MP3 files
produced by Phase 1 (``src/ingestion/audio_downloader.py``), writing results
through the full Medallion warehouse stack: Staging → Cleansed.

Architecture
------------
::

    Phase 1 Output                 Phase 2 Processing
    ─────────────────              ─────────────────────────────────────
    data/raw_audio/               extract_features_for_collection()
      {track_id}.mp3   ──────►      ├─ _load_cached_feature_ids()       (idempotency)
      {track_id}.mp3                ├─ extract_features_for_track()       (per-file)
      ...                           │    ├─ load_audio()                  (audio_loader)
                                    │    └─ extract_features()            (feature_extractor)
                                    ├─ land_staging_features()            (warehouse: Bronze)
                                    └─ build_cleansed_features()          (warehouse: Silver)

Bridge Key
----------
The ``spotify_track_id`` is derived directly from the MP3 filename stem::

    data/raw_audio/3abc123.mp3  →  spotify_track_id = "3abc123"

This is ADR-005: the filename IS the bridge key — no lookup table needed.

Idempotency
-----------
``_load_cached_feature_ids()`` reads the set of ``spotify_track_id`` values
already present in ``data/warehouse/cleansed/cleansed_features.parquet``.
Any track already in that set is skipped, making repeated runs safe and fast.

Error Resilience
----------------
Each track is wrapped in a ``try/except`` block. A corrupted MP3, a file
that is too short (< ``MIN_DURATION_SEC``), or a memory error on an unusually
long track will be logged and skipped — the batch always continues.

References
----------
* CLAUDE_INSTRUCTIONS.md — ADR-004, ADR-005, ADR-006
* src/dsp/feature_extractor.py — ``extract_features()`` + ``TrackFeatures``
* src/dsp/audio_loader.py — ``load_audio()``, ``MIN_DURATION_SEC``
* src/warehouse/staging.py — ``land_staging_features()``
* src/warehouse/cleansed.py — ``build_cleansed_features()``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .audio_loader import load_audio
from .config import DSPConfig
from .feature_extractor import TrackFeatures, extract_features

logger = logging.getLogger(__name__)

# ── Canonical path constants ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_AUDIO_DIR = _PROJECT_ROOT / "data" / "raw_audio"
_CLEANSED_FEATURES_PATH = (
    _PROJECT_ROOT / "data" / "warehouse" / "cleansed" / "cleansed_features.parquet"
)

# MP3 is the only format Phase 1 produces.  We also accept WAV here so that
# the test suite can write synthetic signals without needing ffmpeg.
_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _load_cached_feature_ids(
    features_path: Optional[Path] = None,
) -> set[str]:
    """Return the set of ``spotify_track_id`` values already in the cleansed layer.

    Reads only the ``spotify_track_id`` column (columnar Parquet pushdown) to
    minimise memory usage even when the feature table has 77+ columns.

    Args:
        features_path: Path to the cleansed features Parquet file.  Defaults to
                       ``data/warehouse/cleansed/cleansed_features.parquet``.

    Returns:
        A :class:`set` of track ID strings.  Returns an empty set if the file
        does not exist or cannot be read (handles a fresh / clean environment
        gracefully without raising).
    """
    path = features_path or _CLEANSED_FEATURES_PATH
    if not Path(path).exists():
        logger.debug("Cleansed features Parquet not found (%s) — cache is empty.", path)
        return set()

    try:
        df = pd.read_parquet(path, engine="pyarrow", columns=["spotify_track_id"])
        ids: set[str] = set(df["spotify_track_id"].dropna().astype(str).tolist())
        logger.debug("Loaded %d cached feature IDs from %s.", len(ids), Path(path).name)
        return ids
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not read cached feature IDs from %s — treating cache as empty: %s",
            path,
            exc,
        )
        return set()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 2.1 — SINGLE-TRACK EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def extract_features_for_track(
    audio_path: Path,
    config: Optional[DSPConfig] = None,
) -> Optional[dict]:
    """Extract the full 77-dimensional feature vector from a single audio file.

    Derives the ``spotify_track_id`` bridge key from the audio filename stem
    (e.g., ``data/raw_audio/3abc123.mp3`` → ``"3abc123"``), then runs the
    standard DSP pipeline.

    Args:
        audio_path: Path to the audio file.  Must be a format supported by
                    :func:`~src.dsp.audio_loader.load_audio` (``.mp3``, ``.wav``,
                    ``.flac``, etc.).
        config:     Optional :class:`~src.dsp.config.DSPConfig` override.
                    Defaults (22 050 Hz, 128 mel bands, 13 MFCCs) are used when
                    ``None``.

    Returns:
        A flat :class:`dict` containing ``spotify_track_id`` plus all scalar
        feature columns produced by
        :meth:`~src.dsp.feature_extractor.TrackFeatures.to_summary_dict`.
        Returns ``None`` if loading or extraction fails for any reason.

    Raises:
        Nothing — all exceptions are caught and logged; ``None`` is returned
        on any failure so that batch callers can continue safely.
    """
    audio_path = Path(audio_path)
    spotify_track_id = audio_path.stem

    if config is None:
        config = DSPConfig()

    try:
        signal = load_audio(audio_path, config=config)
    except FileNotFoundError as exc:
        logger.error("Audio file not found for %s: %s", spotify_track_id, exc)
        return None
    except ValueError as exc:
        # Covers: unsupported format, file too short (< MIN_DURATION_SEC)
        logger.error("Audio validation failed for %s: %s", spotify_track_id, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error loading audio for %s: %s", spotify_track_id, exc)
        return None

    try:
        track_features: TrackFeatures = extract_features(signal, config=config)
    except MemoryError as exc:
        logger.error(
            "MemoryError during feature extraction for %s "
            "(file may be too long): %s",
            spotify_track_id,
            exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Feature extraction failed for %s: %s", spotify_track_id, exc
        )
        return None

    # Build the flat row dict; attach the mandatory bridge key.
    row: dict = track_features.to_summary_dict()
    row["spotify_track_id"] = spotify_track_id

    logger.debug(
        "Extracted %d features for spotify_track_id=%s (%.1fs)",
        len(row),
        spotify_track_id,
        signal.duration_sec,
    )
    return row


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK 2.1 (BATCH) + 2.2 (CACHE) + 2.3 (ERROR RESILIENCE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def extract_features_for_collection(
    tracks_df: Optional[pd.DataFrame] = None,
    config: Optional[DSPConfig] = None,
    audio_dir: Path = RAW_AUDIO_DIR,
) -> pd.DataFrame:
    """Extract 77-dimensional DSP features for a collection of MP3 files.

    Discovers audio files in *audio_dir*, applies the idempotency cache
    (``_load_cached_feature_ids``), runs per-track extraction with full error
    isolation, then lands results through the Medallion pipeline
    (Staging → Cleansed).

    Args:
        tracks_df: Optional :class:`~pandas.DataFrame` whose ``spotify_track_id``
                   column restricts which files are processed.  When provided,
                   only files whose stem matches a ``spotify_track_id`` in this
                   DataFrame are extracted.  When ``None``, ALL audio files found
                   in *audio_dir* are candidates.
        config:    Optional :class:`~src.dsp.config.DSPConfig`.  Defaults are used
                   when ``None``.
        audio_dir: Directory containing the downloaded MP3 files.  Defaults to
                   ``data/raw_audio/``.

    Returns:
        A :class:`~pandas.DataFrame` with one row per successfully extracted
        track.  Columns: ``spotify_track_id`` + all scalar feature columns
        produced by :meth:`~src.dsp.feature_extractor.TrackFeatures.to_summary_dict`.
        Returns an empty DataFrame when no tracks are extracted (not an error).

    Side Effects:
        On a non-empty result, this function:

        1. Calls :func:`~src.warehouse.staging.land_staging_features` to land
           raw features in the Staging (Bronze) layer.
        2. Calls :func:`~src.warehouse.cleansed.build_cleansed_features` to
           rebuild the Cleansed (Silver) layer, incorporating the new rows.
    """
    audio_dir = Path(audio_dir)
    if config is None:
        config = DSPConfig()

    # ── Discover candidate audio files ────────────────────────────────────────
    if not audio_dir.exists():
        logger.warning(
            "Audio directory does not exist: %s — returning empty DataFrame.", audio_dir
        )
        return pd.DataFrame()

    all_audio_files: list[Path] = sorted(
        f
        for f in audio_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS
    )

    if not all_audio_files:
        logger.warning("No audio files found in %s.", audio_dir)
        return pd.DataFrame()

    # ── Filter to requested track IDs (if tracks_df provided) ─────────────────
    if tracks_df is not None and not tracks_df.empty:
        if "spotify_track_id" not in tracks_df.columns:
            raise ValueError(
                "tracks_df must contain a 'spotify_track_id' column to filter "
                "audio files.  Received columns: " + str(list(tracks_df.columns))
            )
        requested_ids: set[str] = set(tracks_df["spotify_track_id"].dropna().astype(str))
        candidate_files = [f for f in all_audio_files if f.stem in requested_ids]
        logger.info(
            "Filtering to %d requested tracks (from %d files in %s).",
            len(candidate_files),
            len(all_audio_files),
            audio_dir.name,
        )
    else:
        candidate_files = all_audio_files

    if not candidate_files:
        logger.info("No matching audio files found after filtering.")
        return pd.DataFrame()

    # ── Load idempotency cache ─────────────────────────────────────────────────
    cached_ids: set[str] = _load_cached_feature_ids()
    logger.info(
        "Idempotency cache: %d already-extracted track(s) will be skipped.",
        len(cached_ids),
    )

    # ── Per-track extraction ───────────────────────────────────────────────────
    successful_rows: list[dict] = []
    error_records: list[dict] = []
    n_skipped = 0

    total = len(candidate_files)
    logger.info("Starting batch feature extraction: %d candidate file(s).", total)

    for i, audio_path in enumerate(candidate_files, start=1):
        track_id = audio_path.stem

        # ── Idempotency skip ──
        if track_id in cached_ids:
            logger.info(
                "[%d/%d] Skipping %s: features already cached.", i, total, track_id
            )
            n_skipped += 1
            continue

        logger.info("[%d/%d] Extracting features: %s", i, total, audio_path.name)

        # ── Error-isolated extraction ──
        try:
            row = extract_features_for_track(audio_path, config=config)
        except Exception as exc:  # noqa: BLE001 — belt-and-suspenders outer guard
            logger.error(
                "Unhandled exception extracting features for %s: %s", track_id, exc
            )
            error_records.append({"spotify_track_id": track_id, "error": str(exc)})
            continue

        if row is None:
            # extract_features_for_track already logged the specific error.
            error_records.append(
                {
                    "spotify_track_id": track_id,
                    "error": "extract_features_for_track returned None",
                }
            )
            continue

        successful_rows.append(row)

    # ── Batch summary ──────────────────────────────────────────────────────────
    n_extracted = len(successful_rows)
    n_failed = len(error_records)
    logger.info(
        "Extraction complete — Extracted: %d | Skipped (cached): %d | Failed: %d",
        n_extracted,
        n_skipped,
        n_failed,
    )

    if not successful_rows:
        logger.info("No new features extracted — skipping warehouse landing.")
        return pd.DataFrame()

    features_df = pd.DataFrame(successful_rows)

    # ── Medallion warehouse integration ───────────────────────────────────────
    # Import here (not at module top) to avoid circular dependency with the
    # warehouse layer, which may import dsp indirectly.
    try:
        from src.warehouse.staging import land_staging_features
        from src.warehouse.cleansed import build_cleansed_features

        logger.info("Landing %d feature rows to Staging (Bronze)…", n_extracted)
        land_staging_features(features_df)

        logger.info("Triggering Cleansed (Silver) rebuild…")
        build_cleansed_features()

    except ImportError as exc:
        logger.warning(
            "Warehouse modules not available — skipping staging/cleansed integration: %s",
            exc,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Warehouse integration failed (features are still returned in-memory): %s",
            exc,
        )

    return features_df
