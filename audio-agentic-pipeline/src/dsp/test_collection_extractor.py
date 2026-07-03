"""
test_collection_extractor.py — Unit Tests for the Real Audio Extraction Pipeline
==================================================================================
Tests ``src/dsp/collection_extractor.py`` (Phase 2) using synthetic audio signals.

No real MP3 downloads or external API calls are made.  All heavy I/O is mocked:
    - ``src.warehouse.staging.land_staging_features`` → mocked (no disk writes)
    - ``src.warehouse.cleansed.build_cleansed_features`` → mocked (no disk writes)
    - Parquet reads for the idempotency cache → patched with controlled DataFrames
    - librosa DSP calls → real (they run on tiny synthetic WAV signals in memory)

Synthetic audio is written to ``tmp_path`` as WAV files using ``scipy.io.wavfile``
so no ffmpeg dependency is required for the test suite.

Run from the project root:
    pytest src/dsp/test_collection_extractor.py -v
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.dsp.collection_extractor import (
    RAW_AUDIO_DIR,
    _load_cached_feature_ids,
    extract_features_for_collection,
    extract_features_for_track,
)
from src.dsp.config import DSPConfig, SAMPLE_RATE


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _write_synthetic_wav(path: Path, duration_sec: float = 5.0, sr: int = SAMPLE_RATE) -> Path:
    """Write a 440 Hz sine wave as a 16-bit mono WAV file.

    Uses only stdlib ``wave`` so scipy/soundfile is not required.
    """
    n_samples = int(sr * duration_sec)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    samples = (0.5 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())

    return path


def _write_corrupt_wav(path: Path) -> Path:
    """Write a file with a valid .wav suffix but garbage content."""
    path.write_bytes(b"NOT_A_VALID_WAV_FILE_AT_ALL\x00\x01\x02")
    return path


def _write_tiny_wav(path: Path, sr: int = SAMPLE_RATE) -> Path:
    """Write a WAV that is shorter than MIN_DURATION_SEC (0.5s < 1.0s)."""
    return _write_synthetic_wav(path, duration_sec=0.5, sr=sr)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FIXTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture()
def config() -> DSPConfig:
    """Lightweight DSPConfig: fewer mel bands and MFCCs to speed up tests."""
    return DSPConfig(n_mels=32, n_mfcc=4)


@pytest.fixture()
def valid_wav(tmp_path: Path) -> Path:
    """A valid 5-second synthetic WAV with a bridge-key filename."""
    return _write_synthetic_wav(tmp_path / "spotify_abc123.wav")


@pytest.fixture()
def audio_dir_with_files(tmp_path: Path) -> Path:
    """A directory containing 2 valid WAVs and 1 corrupt file."""
    audio_dir = tmp_path / "raw_audio"
    audio_dir.mkdir()
    _write_synthetic_wav(audio_dir / "track_aaa.wav")
    _write_synthetic_wav(audio_dir / "track_bbb.wav")
    _write_corrupt_wav(audio_dir / "track_bad.wav")
    return audio_dir


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 1 — _load_cached_feature_ids()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLoadCachedFeatureIds:
    """Unit tests for the idempotency-cache loader."""

    def test_returns_empty_set_when_file_missing(self, tmp_path: Path) -> None:
        """Non-existent Parquet path → should return empty set (not raise)."""
        result = _load_cached_feature_ids(tmp_path / "nonexistent.parquet")
        assert isinstance(result, set)
        assert len(result) == 0

    def test_returns_ids_from_parquet(self, tmp_path: Path) -> None:
        """Existing Parquet → returns correct set of track IDs."""
        df = pd.DataFrame({"spotify_track_id": ["id_1", "id_2", "id_3"]})
        parquet_path = tmp_path / "cleansed_features.parquet"
        df.to_parquet(parquet_path, engine="pyarrow", index=False)

        result = _load_cached_feature_ids(parquet_path)

        assert result == {"id_1", "id_2", "id_3"}

    def test_returns_empty_set_on_unreadable_parquet(self, tmp_path: Path) -> None:
        """Corrupt Parquet file → should return empty set (not crash)."""
        bad_parquet = tmp_path / "bad.parquet"
        bad_parquet.write_bytes(b"NOT_PARQUET")

        result = _load_cached_feature_ids(bad_parquet)

        assert isinstance(result, set)
        assert len(result) == 0

    def test_handles_null_track_ids(self, tmp_path: Path) -> None:
        """NaN values in spotify_track_id should be dropped silently."""
        df = pd.DataFrame({"spotify_track_id": ["id_ok", None, float("nan")]})
        parquet_path = tmp_path / "features.parquet"
        df.to_parquet(parquet_path, engine="pyarrow", index=False)

        result = _load_cached_feature_ids(parquet_path)

        assert "id_ok" in result
        # NaN / None should not appear as keys
        assert len([x for x in result if x and "nan" in x.lower()]) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 2 — extract_features_for_track()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractFeaturesForTrack:
    """Unit tests for single-track feature extraction."""

    def test_returns_dict_with_bridge_key(
        self, valid_wav: Path, config: DSPConfig
    ) -> None:
        """Successful extraction must include spotify_track_id in the result."""
        result = extract_features_for_track(valid_wav, config=config)

        assert result is not None
        assert "spotify_track_id" in result
        assert result["spotify_track_id"] == "spotify_abc123"

    def test_bridge_key_derived_from_filename_stem(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """Bridge key must equal the filename stem (not the full path)."""
        wav = _write_synthetic_wav(tmp_path / "my_custom_id.wav")
        result = extract_features_for_track(wav, config=config)

        assert result is not None
        assert result["spotify_track_id"] == "my_custom_id"

    def test_returns_feature_columns(self, valid_wav: Path, config: DSPConfig) -> None:
        """Result must contain key DSP feature columns."""
        result = extract_features_for_track(valid_wav, config=config)

        assert result is not None
        for expected_col in ("tempo_bpm", "rms_mean", "zcr_mean",
                              "spectral_centroid_mean", "harmonic_ratio"):
            assert expected_col in result, f"Missing column: {expected_col}"

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path, config: DSPConfig) -> None:
        """Passing a non-existent path → returns None (does not raise)."""
        missing = tmp_path / "does_not_exist.mp3"
        result = extract_features_for_track(missing, config=config)
        assert result is None

    def test_returns_none_for_corrupt_file(self, tmp_path: Path, config: DSPConfig) -> None:
        """A corrupt file that librosa cannot decode → returns None (does not raise)."""
        bad = _write_corrupt_wav(tmp_path / "bad_track.wav")
        result = extract_features_for_track(bad, config=config)
        assert result is None

    def test_returns_none_for_too_short_file(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """A sub-second clip fails audio_loader validation → returns None gracefully."""
        short = _write_tiny_wav(tmp_path / "short_track.wav")
        result = extract_features_for_track(short, config=config)
        assert result is None

    def test_uses_default_config_when_none_given(self, valid_wav: Path) -> None:
        """When config=None, defaults should be used without error."""
        result = extract_features_for_track(valid_wav, config=None)
        assert result is not None
        assert "spotify_track_id" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 3 — extract_features_for_collection()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractFeaturesForCollection:
    """Integration-style unit tests for the batch extraction orchestrator."""

    # Sentinel: patch warehouse integrations so tests stay unit-level.
    # These are patched at the SOURCE module level because collection_extractor
    # imports them lazily (inside the function body) to avoid circular imports.
    _STAGING_PATCH = "src.warehouse.staging.land_staging_features"
    _CLEANSED_PATCH = "src.warehouse.cleansed.build_cleansed_features"
    _CACHE_PATCH = "src.dsp.collection_extractor._load_cached_feature_ids"

    def test_returns_empty_df_when_no_audio_dir(self, tmp_path: Path, config: DSPConfig) -> None:
        """Non-existent audio directory → empty DataFrame, no crash."""
        result = extract_features_for_collection(
            audio_dir=tmp_path / "nonexistent",
            config=config,
        )
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_empty_df_when_dir_has_no_audio(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """Directory with no audio files → empty DataFrame."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch(self._CACHE_PATCH, return_value=set()):
            result = extract_features_for_collection(audio_dir=empty_dir, config=config)
        assert result.empty

    def test_extracts_valid_files_returns_dataframe(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """Two valid WAVs and one corrupt → DataFrame with exactly 2 rows."""
        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH) as mock_stage, \
             patch(self._CLEANSED_PATCH) as mock_cleanse:

            result = extract_features_for_collection(
                audio_dir=audio_dir_with_files, config=config
            )

        # The corrupt file is silently skipped; 2 valid files succeed.
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "spotify_track_id" in result.columns
        assert set(result["spotify_track_id"]) == {"track_aaa", "track_bbb"}

    def test_warehouse_integration_called_on_success(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """When extraction succeeds, staging and cleansed must be called once each."""
        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH) as mock_stage, \
             patch(self._CLEANSED_PATCH) as mock_cleanse:

            extract_features_for_collection(
                audio_dir=audio_dir_with_files, config=config
            )

        mock_stage.assert_called_once()
        mock_cleanse.assert_called_once()

    def test_warehouse_not_called_when_all_skipped(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """All tracks already cached → warehouse integration must NOT be called."""
        cached = {"track_aaa", "track_bbb", "track_bad"}
        with patch(self._CACHE_PATCH, return_value=cached), \
             patch(self._STAGING_PATCH) as mock_stage, \
             patch(self._CLEANSED_PATCH) as mock_cleanse:

            result = extract_features_for_collection(
                audio_dir=audio_dir_with_files, config=config
            )

        assert result.empty
        mock_stage.assert_not_called()
        mock_cleanse.assert_not_called()

    def test_idempotent_second_run_skips_cached(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """Tracks in the cache must be skipped (simulates second pipeline run)."""
        audio_dir = tmp_path / "raw_audio"
        audio_dir.mkdir()
        _write_synthetic_wav(audio_dir / "cached_track.wav")
        _write_synthetic_wav(audio_dir / "new_track.wav")

        cached = {"cached_track"}

        with patch(self._CACHE_PATCH, return_value=cached), \
             patch(self._STAGING_PATCH), \
             patch(self._CLEANSED_PATCH):

            result = extract_features_for_collection(audio_dir=audio_dir, config=config)

        # Only the new (uncached) track should appear.
        assert len(result) == 1
        assert result.iloc[0]["spotify_track_id"] == "new_track"

    def test_corrupt_file_does_not_crash_batch(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """A single corrupt file must not stop processing of remaining tracks."""
        audio_dir = tmp_path / "raw_audio"
        audio_dir.mkdir()
        _write_synthetic_wav(audio_dir / "good_track.wav")
        _write_corrupt_wav(audio_dir / "bad_track.wav")

        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH), \
             patch(self._CLEANSED_PATCH):

            result = extract_features_for_collection(audio_dir=audio_dir, config=config)

        # Only good_track succeeds; bad_track is silently skipped.
        assert len(result) == 1
        assert result.iloc[0]["spotify_track_id"] == "good_track"

    def test_tracks_df_filter_limits_extraction(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """When tracks_df is provided, only matching files should be processed."""
        # Only request track_aaa — track_bbb should be ignored.
        tracks_df = pd.DataFrame({"spotify_track_id": ["track_aaa"]})

        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH), \
             patch(self._CLEANSED_PATCH):

            result = extract_features_for_collection(
                tracks_df=tracks_df,
                audio_dir=audio_dir_with_files,
                config=config,
            )

        assert len(result) == 1
        assert result.iloc[0]["spotify_track_id"] == "track_aaa"

    def test_raises_if_tracks_df_missing_id_column(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """tracks_df without 'spotify_track_id' column → should raise ValueError."""
        bad_df = pd.DataFrame({"track_name": ["Song A"]})

        with patch(self._CACHE_PATCH, return_value=set()), \
             pytest.raises(ValueError, match="spotify_track_id"):
            extract_features_for_collection(
                tracks_df=bad_df,
                audio_dir=audio_dir_with_files,
                config=config,
            )

    def test_result_has_bridge_key_and_feature_columns(
        self, tmp_path: Path, config: DSPConfig
    ) -> None:
        """Result DataFrame must have spotify_track_id plus key DSP columns."""
        audio_dir = tmp_path / "raw_audio"
        audio_dir.mkdir()
        _write_synthetic_wav(audio_dir / "testtrack.wav")

        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH), \
             patch(self._CLEANSED_PATCH):

            result = extract_features_for_collection(audio_dir=audio_dir, config=config)

        assert "spotify_track_id" in result.columns
        for col in ("tempo_bpm", "rms_mean", "zcr_mean", "harmonic_ratio"):
            assert col in result.columns, f"Missing DSP column: {col}"

    def test_empty_tracks_df_processes_all_audio(
        self, audio_dir_with_files: Path, config: DSPConfig
    ) -> None:
        """An explicitly empty tracks_df should fall back to processing all files."""
        empty_df = pd.DataFrame()

        with patch(self._CACHE_PATCH, return_value=set()), \
             patch(self._STAGING_PATCH), \
             patch(self._CLEANSED_PATCH):

            result = extract_features_for_collection(
                tracks_df=empty_df,
                audio_dir=audio_dir_with_files,
                config=config,
            )

        # 2 valid + 1 corrupt → 2 successes
        assert len(result) == 2
