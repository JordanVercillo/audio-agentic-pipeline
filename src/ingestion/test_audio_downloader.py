"""
test_audio_downloader.py — Unit Tests for the Audio Acquisition Layer
=======================================================================
Tests the components of ``audio_downloader.py`` WITHOUT making real
network requests or filesystem writes to ``data/raw_audio/``.

All external I/O is mocked:
    - ``yt_dlp.YoutubeDL``         → mocked entirely (no real downloads)
    - ``time.sleep``               → mocked (no real delays in tests)
    - Parquet file reads           → mocked with controlled DataFrames
    - Filesystem existence checks  → patched via ``tmp_path`` fixtures

Run from the project root:
    pytest src/ingestion/test_audio_downloader.py -v
"""

from __future__ import annotations

# ── Allow running before installation (add src to path) ──────────────────────
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.ingestion.audio_downloader import (
    RAW_AUDIO_DIR,
    DownloadConfig,
    download_audio_for_tracks,
    download_track_audio,
    resolve_youtube_url,
    should_skip_download,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FIXTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture()
def default_config(tmp_path: Path) -> DownloadConfig:
    """A DownloadConfig pointing to a temporary directory."""
    return DownloadConfig(output_dir=tmp_path)


@pytest.fixture()
def sample_tracks_df() -> pd.DataFrame:
    """A minimal DataFrame mimicking fetch_all_top_items() output."""
    return pd.DataFrame(
        {
            "spotify_track_id": ["track_aaa", "track_bbb", "track_ccc"],
            "track_name": ["Song A", "Song B", "Song C"],
            "artist_names": ["Artist X", "Artist Y", "Artist Z"],
        }
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 1 — DownloadConfig defaults
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDownloadConfig:
    """Verify that DownloadConfig dataclass field defaults are correct."""

    def test_default_output_dir(self) -> None:
        config = DownloadConfig()
        assert config.output_dir == RAW_AUDIO_DIR

    def test_default_min_delay(self) -> None:
        config = DownloadConfig()
        assert config.min_delay == 5.0

    def test_default_max_delay(self) -> None:
        config = DownloadConfig()
        assert config.max_delay == 30.0

    def test_default_max_retries(self) -> None:
        config = DownloadConfig()
        assert config.max_retries == 3

    def test_default_backoff_base(self) -> None:
        config = DownloadConfig()
        assert config.backoff_base == 2.0

    def test_default_error_delay(self) -> None:
        config = DownloadConfig()
        assert config.error_delay == 60.0

    def test_custom_values(self) -> None:
        config = DownloadConfig(min_delay=1.0, max_delay=5.0, max_retries=1)
        assert config.min_delay == 1.0
        assert config.max_delay == 5.0
        assert config.max_retries == 1

    def test_output_dir_is_path(self) -> None:
        config = DownloadConfig()
        assert isinstance(config.output_dir, Path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 2 — should_skip_download()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestShouldSkipDownload:
    """Unit tests for the idempotent skip-check logic."""

    def test_returns_false_when_no_file_and_no_parquet(
        self, tmp_path: Path
    ) -> None:
        """Neither file condition met → should return False."""
        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            tmp_path / "nonexistent.parquet",
        ):
            result = should_skip_download("track_xyz", config=config)

        assert result is False

    def test_returns_true_when_mp3_exists(self, tmp_path: Path) -> None:
        """MP3 file already on disk → should skip."""
        track_id = "track_123"
        mp3 = tmp_path / f"{track_id}.mp3"
        mp3.write_bytes(b"\xff" * 1024)  # non-zero content

        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            tmp_path / "nonexistent.parquet",
        ):
            result = should_skip_download(track_id, config=config)

        assert result is True

    def test_returns_false_when_mp3_is_empty(self, tmp_path: Path) -> None:
        """MP3 exists but is zero-bytes → should NOT skip (re-download)."""
        track_id = "track_empty"
        mp3 = tmp_path / f"{track_id}.mp3"
        mp3.write_bytes(b"")  # zero-byte file

        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            tmp_path / "nonexistent.parquet",
        ):
            result = should_skip_download(track_id, config=config)

        assert result is False

    def test_returns_true_when_track_in_parquet(self, tmp_path: Path) -> None:
        """Track already has features in the cleansed warehouse → should skip."""
        track_id = "track_456"
        features_df = pd.DataFrame({"spotify_track_id": [track_id, "other_track"]})
        parquet_path = tmp_path / "cleansed_features.parquet"
        features_df.to_parquet(parquet_path, engine="pyarrow", index=False)

        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            parquet_path,
        ):
            result = should_skip_download(track_id, config=config)

        assert result is True

    def test_returns_false_when_track_not_in_parquet(self, tmp_path: Path) -> None:
        """Parquet exists but does not contain this track → should NOT skip."""
        track_id = "track_new"
        features_df = pd.DataFrame({"spotify_track_id": ["other_track"]})
        parquet_path = tmp_path / "cleansed_features.parquet"
        features_df.to_parquet(parquet_path, engine="pyarrow", index=False)

        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            parquet_path,
        ):
            result = should_skip_download(track_id, config=config)

        assert result is False

    def test_handles_missing_parquet_gracefully(self, tmp_path: Path) -> None:
        """Missing Parquet file should not raise — returns False."""
        config = DownloadConfig(output_dir=tmp_path)

        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            tmp_path / "does_not_exist.parquet",
        ):
            result = should_skip_download("track_no_parquet", config=config)

        assert result is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 3 — resolve_youtube_url()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestFfmpegResolution:
    """The live bug (2026-07-23): the webapp's PATH put Anaconda's ffmpeg
    first — a build with NO libmp3lame — so every acquisition downloaded fine
    then died at conversion with "Encoder not found". The first fix only
    DETECTED the bad binary and returned None, handing yt-dlp back to that
    same bad ffmpeg. The resolver must keep looking past a lame-less build."""

    def test_skips_a_lame_less_ffmpeg_and_keeps_looking(self, monkeypatch, tmp_path):
        from src.ingestion import audio_downloader as ad
        bad = tmp_path / "anaconda" / "ffmpeg.exe"
        good = tmp_path / "full_build" / "ffmpeg.exe"
        for p in (bad, good):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        monkeypatch.setattr(ad, "_mp3_capable_candidates",
                            lambda: [str(bad), str(good)])
        monkeypatch.setattr(ad, "_can_encode_mp3", lambda exe: exe == str(good))
        assert ad.ffmpeg_location() == str(good.parent)   # skipped the bad one

    def test_returns_none_when_nothing_can_encode(self, monkeypatch):
        from src.ingestion import audio_downloader as ad
        monkeypatch.setattr(ad, "_mp3_capable_candidates", lambda: ["/x/ffmpeg"])
        monkeypatch.setattr(ad, "_can_encode_mp3", lambda exe: False)
        assert ad.ffmpeg_location() is None               # honest, and it logs

    def test_override_is_tried_first(self, monkeypatch, tmp_path):
        from src.ingestion import audio_downloader as ad
        exe = tmp_path / "ops" / "ffmpeg.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
        monkeypatch.setenv("FFMPEG_LOCATION", str(exe.parent))
        assert str(exe) in ad._mp3_capable_candidates()[:1]

    def test_candidates_scan_every_path_entry_not_just_the_first(
            self, monkeypatch, tmp_path):
        # shutil.which returns only the FIRST hit — which was the broken one.
        from src.ingestion import audio_downloader as ad
        first, second = tmp_path / "a", tmp_path / "b"
        for d in (first, second):
            d.mkdir()
            (d / "ffmpeg.exe").write_text("x")
        monkeypatch.delenv("FFMPEG_LOCATION", raising=False)
        monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second)]))
        found = ad._mp3_capable_candidates()
        assert str(first / "ffmpeg.exe") in found
        assert str(second / "ffmpeg.exe") in found        # the shadowed one too


class TestResolveYoutubeUrl:
    """Unit tests for the YouTube search resolver — yt_dlp is mocked."""

    def _make_ydl_mock(self, entries: list[dict]) -> MagicMock:
        """Return a context-manager mock for yt_dlp.YoutubeDL."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": entries}
        return mock_ydl

    def test_returns_url_for_good_match(self) -> None:
        """Should return the URL of the highest-scoring candidate."""
        entries = [
            {
                "title": "Queen - Bohemian Rhapsody (Official Audio)",
                "url": "https://www.youtube.com/watch?v=abc123",
            },
            {
                "title": "Bohemian Rhapsody - Live at Wembley",
                "url": "https://www.youtube.com/watch?v=live456",
            },
        ]
        mock_ydl = self._make_ydl_mock(entries)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = resolve_youtube_url("Bohemian Rhapsody", "Queen")

        # The official audio should win over the live recording.
        assert result == "https://www.youtube.com/watch?v=abc123"

    def test_returns_none_when_no_entries(self) -> None:
        """Empty search results → should return None gracefully."""
        mock_ydl = self._make_ydl_mock(entries=[])

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = resolve_youtube_url("Nonexistent Track", "Unknown Artist")

        assert result is None

    def test_returns_none_on_download_error(self) -> None:
        """DownloadError from yt_dlp → should return None (not raise)."""
        import yt_dlp

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError("search failed")

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = resolve_youtube_url("Any Track", "Any Artist")

        assert result is None

    def test_prefer_official_appends_suffix(self) -> None:
        """prefer_official=True should include 'official audio' in the query."""
        mock_ydl = self._make_ydl_mock(entries=[])

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl) as MockYDL:
            resolve_youtube_url("Song", "Artist", prefer_official=True)
            call_args = MockYDL.return_value.__enter__.return_value.extract_info.call_args
            query_string = call_args[0][0]

        assert "official audio" in query_string.lower()

    def test_deprioritises_live_results(self) -> None:
        """Live recordings should score lower than official audio."""
        entries = [
            {
                "title": "Song - Live Performance",
                "url": "https://www.youtube.com/watch?v=live",
            },
            {
                "title": "Song - Official Audio",
                "url": "https://www.youtube.com/watch?v=official",
            },
        ]
        mock_ydl = self._make_ydl_mock(entries)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = resolve_youtube_url("Song", "Artist")

        assert result == "https://www.youtube.com/watch?v=official"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 3b — O2 match hardening (pure scoring, no network)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestO2MatchScoring:
    """Duration-aware candidate scoring (D-22) — pure functions, no yt_dlp."""

    def test_duration_closeness_beats_title_keywords(self) -> None:
        # The wrong-version case O2 exists for: a "(Live)"-less live cut whose
        # only tell is being 90s longer than the studio length.
        from src.ingestion.audio_downloader import pick_best_candidate
        entries = [
            {"title": "Song (Extended Anniversary Edition)", "duration": 330.0,
             "url": "https://y/long"},
            {"title": "Song", "duration": 241.0, "url": "https://y/right"},
        ]
        best = pick_best_candidate(entries, target_duration_s=240.0)
        assert best["url"] == "https://y/right"
        assert best["duration_delta_s"] == pytest.approx(1.0)
        assert 0.0 <= best["confidence"] <= 1.0

    def test_candidate_carries_provenance_fields(self) -> None:
        # Q1/D-51: the match record now carries what the flat entry already had
        # (video id, channel, yt duration, candidate count) — captured, not fetched.
        from src.ingestion.audio_downloader import pick_best_candidate
        entries = [
            {"title": "Song", "duration": 241.0, "url": "https://y/right",
             "id": "vid_right", "channel": "RightVEVO"},
            {"title": "Song (Live)", "duration": 400.0, "url": "https://y/live",
             "id": "vid_live"},
        ]
        best = pick_best_candidate(entries, target_duration_s=240.0)
        assert best["youtube_video_id"] == "vid_right"      # the WINNER's id, not the loser's
        assert best["channel"] == "RightVEVO"
        assert best["youtube_duration_s"] == 241.0
        assert best["candidate_count"] == 2                 # both entries were ranked

    def test_scoring_degrades_gracefully_without_durations(self) -> None:
        from src.ingestion.audio_downloader import score_candidate
        # unknown candidate duration, unknown target — title keywords only
        assert score_candidate("Song - Official Audio", None, None) == 10
        assert score_candidate("Song - Live", 240.0, None) == -15
        assert score_candidate("Song", None, 240.0) == 0

    def test_duration_bands(self) -> None:
        from src.ingestion.audio_downloader import score_candidate
        t = 200.0
        assert score_candidate("Song", 201.0, t) == 25    # ≤3s: near-exact
        assert score_candidate("Song", 208.0, t) == 12    # ≤10s
        assert score_candidate("Song", 220.0, t) == 0     # ≤25s: neutral
        assert score_candidate("Song", 240.0, t) == -10   # ≤45s
        assert score_candidate("Song", 300.0, t) == -30   # way off: live/extended

    def test_never_rejects_only_ranks(self) -> None:
        # Selection + recording ONLY (heuristic-v1): even a terrible sole
        # candidate is returned — rejection thresholds await corpus evidence.
        from src.ingestion.audio_downloader import pick_best_candidate
        entries = [{"title": "Song - Live Cover Karaoke", "duration": 500.0,
                    "url": "https://y/awful"}]
        best = pick_best_candidate(entries, target_duration_s=200.0)
        assert best is not None and best["url"] == "https://y/awful"
        assert best["confidence"] == 0.0  # …but the record says how bad it was

    def test_resolve_match_logs_and_returns_record(self) -> None:
        from src.ingestion.audio_downloader import resolve_youtube_match
        entries = [{"title": "Song - Official Audio", "duration": 240.0,
                    "url": "https://y/ok"}]
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": entries}
        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            match = resolve_youtube_match("Song", "Artist", duration_s=240.0)
        assert match["url"] == "https://y/ok"
        assert match["score"] == 35 and match["confidence"] == 1.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 4 — download_track_audio()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDownloadTrackAudio:
    """Unit tests for the MP3 downloader — yt_dlp is mocked."""

    def _make_download_mock(self, tmp_path: Path, track_id: str) -> MagicMock:
        """Return a yt_dlp mock that writes a fake MP3 as a side effect."""

        def _fake_download(urls: list[str]) -> None:
            mp3 = tmp_path / f"{track_id}.mp3"
            mp3.write_bytes(b"\xff" * 1024)

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = _fake_download
        return mock_ydl

    def test_returns_path_on_success(self, tmp_path: Path) -> None:
        """Successful download should return a Path pointing to the MP3."""
        track_id = "spotify_abc"
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)
        mock_ydl = self._make_download_mock(tmp_path, track_id)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = download_track_audio(
                "https://www.youtube.com/watch?v=fake", track_id, config=config
            )

        assert result is not None
        assert result == tmp_path / f"{track_id}.mp3"
        assert result.exists()

    def test_filename_uses_bridge_key(self, tmp_path: Path) -> None:
        """Output filename must be exactly '{spotify_track_id}.mp3'."""
        track_id = "bridgekey_test"
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)
        mock_ydl = self._make_download_mock(tmp_path, track_id)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = download_track_audio(
                "https://www.youtube.com/watch?v=fake", track_id, config=config
            )

        assert result is not None
        assert result.stem == track_id
        assert result.suffix == ".mp3"

    def test_returns_none_on_download_error(self, tmp_path: Path) -> None:
        """DownloadError from yt_dlp should cause None to be returned (not raised)."""
        import yt_dlp

        track_id = "bad_track"
        config = DownloadConfig(output_dir=tmp_path, max_retries=2, backoff_base=0.01)
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = yt_dlp.utils.DownloadError("not available")

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
             patch("time.sleep"):
            result = download_track_audio(
                "https://www.youtube.com/watch?v=bad", track_id, config=config
            )

        assert result is None

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """output_dir should be created automatically if it does not exist."""
        track_id = "mkdir_test"
        deep_dir = tmp_path / "deep" / "nested" / "dir"
        config = DownloadConfig(output_dir=deep_dir, max_retries=1)
        mock_ydl = self._make_download_mock(deep_dir, track_id)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            download_track_audio(
                "https://www.youtube.com/watch?v=fake", track_id, config=config
            )

        assert deep_dir.exists()

    def test_http_429_triggers_error_delay(self, tmp_path: Path) -> None:
        """HTTP 429 response should trigger the configured error_delay."""
        import yt_dlp

        track_id = "rate_limited"
        config = DownloadConfig(
            output_dir=tmp_path,
            max_retries=1,
            error_delay=10.0,
            backoff_base=2.0,
        )
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = yt_dlp.utils.DownloadError(
            "HTTP Error 429: Too Many Requests"
        )

        sleep_calls: list[float] = []

        def _record_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl), \
             patch("time.sleep", side_effect=_record_sleep):
            download_track_audio(
                "https://www.youtube.com/watch?v=fake", track_id, config=config
            )

        assert len(sleep_calls) >= 1
        assert sleep_calls[0] >= config.error_delay


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEST 5 — download_audio_for_tracks()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDownloadAudioForTracks:
    """Integration-style unit tests for the batch orchestrator."""

    def test_empty_dataframe_returns_empty_summary(self) -> None:
        """An empty input DataFrame should return an empty summary DataFrame."""
        result = download_audio_for_tracks(pd.DataFrame())

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert set(result.columns) == {
            "spotify_track_id",
            "local_audio_path",
            "download_status",
            "error_message",
        }

    def test_returns_one_row_per_input_track(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """Summary DataFrame must have exactly one row per input track."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=True,
        ), patch("time.sleep"):
            result = download_audio_for_tracks(sample_tracks_df, config=config)

        assert len(result) == len(sample_tracks_df)

    def test_all_statuses_on_skipped(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """When all tracks are skipped, download_status should be 'skipped' for each."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=True,
        ):
            result = download_audio_for_tracks(sample_tracks_df, config=config)

        assert (result["download_status"] == "skipped").all()

    def test_status_no_match_when_no_youtube_url(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """No YouTube result → download_status should be 'no_match'."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=False,
        ), patch(
            "src.ingestion.audio_downloader.resolve_youtube_url",
            return_value=None,
        ), patch("time.sleep"):
            result = download_audio_for_tracks(sample_tracks_df, config=config)

        assert (result["download_status"] == "no_match").all()

    def test_status_success_on_download(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """Successful downloads should yield 'success' status with a local_audio_path."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)
        fake_path = tmp_path / "track_aaa.mp3"
        fake_path.write_bytes(b"\xff" * 512)

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=False,
        ), patch(
            "src.ingestion.audio_downloader.resolve_youtube_url",
            return_value="https://youtube.com/watch?v=fake",
        ), patch(
            "src.ingestion.audio_downloader.download_track_audio",
            return_value=fake_path,
        ), patch("time.sleep"):
            result = download_audio_for_tracks(
                sample_tracks_df.head(1), config=config
            )

        assert result.iloc[0]["download_status"] == "success"
        assert result.iloc[0]["local_audio_path"] == str(fake_path)

    def test_status_failed_on_download_failure(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """download_track_audio returning None should yield 'failed' status."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=False,
        ), patch(
            "src.ingestion.audio_downloader.resolve_youtube_url",
            return_value="https://youtube.com/watch?v=fake",
        ), patch(
            "src.ingestion.audio_downloader.download_track_audio",
            return_value=None,
        ), patch("time.sleep"):
            result = download_audio_for_tracks(
                sample_tracks_df.head(1), config=config
            )

        assert result.iloc[0]["download_status"] == "failed"
        assert result.iloc[0]["error_message"] != ""

    def test_rate_limiting_delay_is_called(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """time.sleep should be called between downloads (not after skips)."""
        config = DownloadConfig(
            output_dir=tmp_path, min_delay=1.0, max_delay=2.0, max_retries=1
        )

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=False,
        ), patch(
            "src.ingestion.audio_downloader.resolve_youtube_url",
            return_value="https://youtube.com/watch?v=fake",
        ), patch(
            "src.ingestion.audio_downloader.download_track_audio",
            return_value=None,
        ), patch("time.sleep") as mock_sleep:
            download_audio_for_tracks(sample_tracks_df, config=config)

        # At least one sleep call with a value in [min_delay, max_delay].
        assert mock_sleep.call_count >= 1
        for call_args in mock_sleep.call_args_list:
            delay = call_args[0][0]
            assert config.min_delay <= delay <= config.max_delay

    def test_raises_on_missing_required_columns(self, tmp_path: Path) -> None:
        """DataFrame missing required columns should raise ValueError."""
        bad_df = pd.DataFrame({"track_name": ["Song A"]})
        config = DownloadConfig(output_dir=tmp_path)

        with pytest.raises(ValueError, match="missing required columns"):
            download_audio_for_tracks(bad_df, config=config)

    def test_idempotent_second_run_all_skipped(
        self, sample_tracks_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """Simulates running the pipeline twice — second run should skip everything."""
        config = DownloadConfig(output_dir=tmp_path, max_retries=1)

        # First run: all downloads succeed.
        def _create_mp3(track_id: str, **_kwargs: object) -> Path:
            p = tmp_path / f"{track_id}.mp3"
            p.write_bytes(b"\xff" * 512)
            return p

        with patch(
            "src.ingestion.audio_downloader.should_skip_download",
            return_value=False,
        ), patch(
            "src.ingestion.audio_downloader.resolve_youtube_url",
            return_value="https://youtube.com/watch?v=fake",
        ), patch(
            "src.ingestion.audio_downloader.download_track_audio",
            side_effect=lambda url, tid, config=None: _create_mp3(tid),
        ), patch("time.sleep"):
            first = download_audio_for_tracks(sample_tracks_df, config=config)

        assert (first["download_status"] == "success").all()

        # Second run: should_skip_download reads from disk → all skipped.
        with patch(
            "src.ingestion.audio_downloader._CLEANSED_FEATURES_PATH",
            tmp_path / "nonexistent.parquet",
        ):
            second = download_audio_for_tracks(sample_tracks_df, config=config)

        assert (second["download_status"] == "skipped").all()
