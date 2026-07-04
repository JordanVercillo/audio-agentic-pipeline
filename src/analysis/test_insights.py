"""
test_insights.py — Insight engine tests (synthetic data only)
==============================================================
SPEC P2 acceptance: unit-tested on a synthetic fact table; JSON schema
stable. No warehouse, no API, no LLM — pure-function coverage.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.clustering import VECTOR_77_COLUMNS
from src.analysis.drift import DRIFT_FEATURE_COLS
from src.analysis.insights import (
    INSIGHTS_SCHEMA_VERSION,
    build_insights,
    render_markdown,
)

# The stable top-level schema contract (P5 MCP + P8 RAG read this).
EXPECTED_TOP_LEVEL_KEYS = {
    "schema_version", "generated_at", "corpus", "drift",
    "clusters", "persistence", "superlatives", "genres",
}


def _synthetic_fact(seed: int = 11) -> pd.DataFrame:
    """
    9 unique tracks across 3 time ranges with crafted feature values:
    - track t0 appears in ALL three ranges (persistent favorite, rank 1)
    - short_term is loud/fast/bright, long_term quiet/slow/dark → real drift
    - track 's_max' is the crafted short_term argmax for every superlative
    """
    rng = np.random.default_rng(seed)
    rows = []

    def base_features(level: float) -> dict:
        d = {c: float(rng.normal(level, 0.05)) for c in DRIFT_FEATURE_COLS}
        return d

    # persistent favorite across all ranges
    for tr in ["short_term", "medium_term", "long_term"]:
        rows.append({
            "spotify_track_id": "t0", "track_name": "Evergreen",
            "primary_artist_name": "Artist A", "time_range": tr, "rank": 1,
            **base_features(1.0),
        })
    # range-specific tracks with drifting levels
    for i, (tr, level) in enumerate([
        ("short_term", 2.0), ("short_term", 2.1),
        ("medium_term", 1.0), ("medium_term", 1.1),
        ("long_term", 0.2), ("long_term", 0.3),
    ]):
        rows.append({
            "spotify_track_id": f"t{i+1}", "track_name": f"Track {i+1}",
            "primary_artist_name": f"Artist {'AB'[i % 2]}", "time_range": tr,
            "rank": i + 2, **base_features(level),
        })
    # crafted short_term superlative winner
    winner = {
        "spotify_track_id": "s_max", "track_name": "Peak Energy",
        "primary_artist_name": "Artist Max", "time_range": "short_term",
        "rank": 9, **base_features(2.0),
    }
    winner.update({"rms_mean": 99.0, "tempo_bpm": 999.0,
                   "harmonic_ratio": 9.9, "spectral_centroid_mean": 9999.0})
    rows.append(winner)

    return pd.DataFrame(rows).reset_index(drop=True)


def _synthetic_assignments(fact: pd.DataFrame) -> pd.DataFrame:
    tracks = fact.drop_duplicates("spotify_track_id")
    return pd.DataFrame({
        "spotify_track_id": tracks["spotify_track_id"].values,
        "cluster_id": [i % 2 for i in range(len(tracks))],
        "umap_x": np.linspace(0, 1, len(tracks)),
        "umap_y": np.linspace(1, 0, len(tracks)),
        "genre_bucket": ["Rock", "Punk & Emo"] * (len(tracks) // 2)
        + ["Rock"] * (len(tracks) % 2),
        "n_time_ranges": [3] + [1] * (len(tracks) - 1),
        "track_name": tracks["track_name"].values,
        "primary_artist_name": tracks["primary_artist_name"].values,
    })


def _synthetic_features(fact: pd.DataFrame, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tracks = fact.drop_duplicates("spotify_track_id")["spotify_track_id"]
    df = pd.DataFrame(
        rng.normal(0, 1, size=(len(tracks), len(VECTOR_77_COLUMNS))),
        columns=VECTOR_77_COLUMNS,
    )
    df.insert(0, "spotify_track_id", tracks.values)
    return df


class TestSchema:
    def test_top_level_keys_stable(self):
        insights = build_insights(_synthetic_fact())
        assert set(insights.keys()) == EXPECTED_TOP_LEVEL_KEYS
        assert insights["schema_version"] == INSIGHTS_SCHEMA_VERSION

    def test_json_serializable(self):
        import json
        insights = build_insights(
            _synthetic_fact(),
            assignments=_synthetic_assignments(_synthetic_fact()),
            features=_synthetic_features(_synthetic_fact()),
        )
        json.dumps(insights)  # raises on numpy types leaking through

    def test_empty_fact_raises(self):
        with pytest.raises(ValueError, match="empty"):
            build_insights(pd.DataFrame())


class TestDrift:
    def test_drift_detected_on_drifting_corpus(self):
        # Corpus is built with strongly shifted feature levels per range —
        # the (standardized-cosine) score must clearly register it, not
        # flatline at ~0 (the unscaled-cosine bug caught on real data).
        insights = build_insights(_synthetic_fact())
        d = insights["drift"]
        assert d["score"] > 0.5  # RMS σ-shift is unbounded above
        assert "Drift" in d["label"]
        assert len(d["top_drivers"]) == 5
        assert set(d["pairwise_distances"]) == {
            "short_term_vs_medium_term", "medium_term_vs_long_term",
            "short_term_vs_long_term",
        }

    def test_constant_corpus_reads_zero_drift(self):
        # Identical features everywhere → z-centroids are zero vectors.
        # Must read 0.0 (no drift), NOT 1.0 (the old degenerate-norm fallback
        # would have called maximal drift on a perfectly stable corpus).
        fact = _synthetic_fact()
        for col in DRIFT_FEATURE_COLS:
            fact[col] = 1.0
        d = build_insights(fact)["drift"]
        assert d["score"] == 0.0
        assert d["stability_score"] == 1.0


class TestSections:
    def test_superlatives_pick_crafted_winner(self):
        insights = build_insights(_synthetic_fact())
        s = insights["superlatives"]
        for key in ("highest_energy", "fastest", "most_acoustic", "brightest"):
            assert s[key]["short_term"]["track_name"] == "Peak Energy"

    def test_persistence_counts(self):
        insights = build_insights(_synthetic_fact())
        p = insights["persistence"]
        assert p["n_all_three"] == 1  # only t0
        assert p["n_single_range"] == 7  # t1..t6 + s_max
        assert p["persistent_favorites"][0]["track_name"] == "Evergreen"

    def test_clusters_unavailable_without_assignments(self):
        insights = build_insights(_synthetic_fact())
        assert insights["clusters"] == {"available": False, "k": None, "clusters": []}

    def test_clusters_populated_with_assignments(self):
        fact = _synthetic_fact()
        insights = build_insights(
            fact,
            assignments=_synthetic_assignments(fact),
            features=_synthetic_features(fact),
        )
        cl = insights["clusters"]
        assert cl["available"] is True
        assert cl["k"] == 2
        assert {c["cluster_id"] for c in cl["clusters"]} == {0, 1}
        assert all("acoustic_label" in c for c in cl["clusters"])

    def test_corpus_counts(self):
        fact = _synthetic_fact()
        insights = build_insights(fact)
        c = insights["corpus"]
        assert c["n_unique_tracks"] == 8
        assert c["n_fact_rows"] == len(fact)
        assert c["time_ranges"] == ["short_term", "medium_term", "long_term"]


class TestMarkdown:
    def test_renders_key_numbers_and_sections(self):
        fact = _synthetic_fact()
        insights = build_insights(
            fact,
            assignments=_synthetic_assignments(fact),
            features=_synthetic_features(fact),
        )
        md = render_markdown(insights)
        assert str(insights["drift"]["score"]) in md
        for heading in ("# 🎧 Taste Insights", "## The drift verdict",
                        "## The neighborhoods", "## Staying power",
                        "## Superlatives", "## Genre profile"):
            assert heading in md
        assert "Executive summary" not in md  # no LLM section by default

    def test_executive_summary_inserted_when_provided(self):
        insights = build_insights(_synthetic_fact())
        md = render_markdown(insights, executive_summary="Your taste is loud.")
        assert "## Executive summary" in md
        assert "Your taste is loud." in md

    def test_deterministic_same_input_same_output(self):
        insights = build_insights(_synthetic_fact())
        assert render_markdown(insights) == render_markdown(insights)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
