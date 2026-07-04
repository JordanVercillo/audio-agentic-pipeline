"""
test_export.py — Portfolio report tests (synthetic data only)
==============================================================
SPEC P4 acceptance support: the report is a single self-contained file
(no filesystem/network image refs), under budget, and autoescapes untrusted
strings (P8 renders other users' libraries through this template).
"""

import base64
import json

import numpy as np
import pandas as pd
import pytest

from src.export.portfolio import (
    REPORT_IMAGES,
    build_report_html,
    render_html,
    top_tracks_by_window,
)

# 1×1 transparent PNG
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _minimal_insights() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-03T00:00:00+00:00",
        "corpus": {"n_fact_rows": 6, "n_unique_tracks": 4,
                   "n_tracks_with_features": 4, "n_unique_artists": 2,
                   "time_ranges": ["short_term", "long_term"],
                   "genre_coverage": {"covered": 3, "total": 4}},
        "drift": {"score": 0.14, "label": "Minimal Drift — stable",
                  "stability_score": 0.86,
                  "pairwise_distances": {"short_term_vs_long_term": 0.14},
                  "top_drivers": []},
        "clusters": {"available": True, "k": 1, "clusters": [
            {"cluster_id": 0, "n_tracks": 4, "acoustic_label": "Loud · Fast",
             "dominant_genre": "Rock", "top_artist": "Artist A"}]},
        "persistence": {"n_single_range": 2, "n_two_ranges": 1, "n_all_three": 1,
                        "persistent_favorites": [
                            {"track_name": "Evergreen", "artist": "Artist A",
                             "avg_rank": 1.0}]},
        "superlatives": {"highest_energy": {
            "short_term": {"track_name": "Loud One", "artist": "Artist B",
                           "value": 0.3}}},
        "genres": {"distribution": {"Rock": 3, "Unknown": 1},
                   "top_artists": [{"artist": "Artist A", "n_tracks": 3}]},
    }


def _fact() -> pd.DataFrame:
    rows = []
    for tr in ["short_term", "long_term"]:
        for i in range(3):
            rows.append({"spotify_track_id": f"{tr}{i}",
                         "track_name": f"Track {i} <{tr}>",
                         "primary_artist_name": "A & B",
                         "time_range": tr, "rank": i + 1})
    return pd.DataFrame(rows)


@pytest.fixture()
def prepared_dirs(tmp_path):
    artifacts = tmp_path / "artifacts"
    modeled = tmp_path / "modeled"
    artifacts.mkdir()
    modeled.mkdir()
    (artifacts / "insights.json").write_text(
        json.dumps(_minimal_insights()), encoding="utf-8")
    for filename in REPORT_IMAGES.values():
        (artifacts / filename).write_bytes(_TINY_PNG)
    _fact().to_parquet(modeled / "fact_listening_features.parquet", index=False)
    return modeled, artifacts


class TestSelfContainment:
    def test_report_is_single_offline_file(self, prepared_dirs):
        modeled, artifacts = prepared_dirs
        out = build_report_html(modeled_dir=modeled, artifacts_dir=artifacts)
        html = out.read_text(encoding="utf-8")

        # every image is an inline data: URI
        assert html.count("data:image/png;base64,") == len(REPORT_IMAGES)
        # no filesystem or network image/script/style references
        assert 'src="http' not in html
        assert 'src="file' not in html
        assert "<script" not in html.lower()
        assert '<link rel="stylesheet"' not in html.lower()

    def test_report_under_budget(self, prepared_dirs):
        modeled, artifacts = prepared_dirs
        out = build_report_html(modeled_dir=modeled, artifacts_dir=artifacts)
        assert out.stat().st_size < 10 * 1_048_576

    def test_key_numbers_present(self, prepared_dirs):
        modeled, artifacts = prepared_dirs
        html = build_report_html(
            modeled_dir=modeled, artifacts_dir=artifacts).read_text(encoding="utf-8")
        assert "0.14" in html                    # drift score
        assert "Loud · Fast" in html             # acoustic cluster label
        assert "Evergreen" in html               # persistent favorite

    def test_missing_inputs_raise_pointed_errors(self, prepared_dirs, tmp_path):
        modeled, artifacts = prepared_dirs
        with pytest.raises(FileNotFoundError, match="build_insights"):
            build_report_html(modeled_dir=modeled, artifacts_dir=tmp_path / "empty")


class TestEscaping:
    def test_untrusted_names_are_escaped(self, prepared_dirs):
        # P8 renders OTHER users' libraries — a malicious track name must
        # never become markup.
        modeled, artifacts = prepared_dirs
        insights = _minimal_insights()
        insights["persistence"]["persistent_favorites"][0]["track_name"] = \
            '<script>alert("x")</script>'
        (artifacts / "insights.json").write_text(json.dumps(insights), encoding="utf-8")

        html = build_report_html(
            modeled_dir=modeled, artifacts_dir=artifacts).read_text(encoding="utf-8")
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_fact_track_names_escaped(self, prepared_dirs):
        modeled, artifacts = prepared_dirs
        html = build_report_html(
            modeled_dir=modeled, artifacts_dir=artifacts).read_text(encoding="utf-8")
        # _fact() names contain "<short_term>" — must arrive escaped
        assert "Track 0 &lt;short_term&gt;" in html


class TestTopTracks:
    def test_shapes_and_order(self):
        shaped = top_tracks_by_window(_fact(), top_n=2)
        assert [w["key"] for w in shaped] == ["short", "long"]
        assert len(shaped[0]["tracks"]) == 2
        assert shaped[0]["tracks"][0]["track_name"].startswith("Track 0")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
