"""
test_clustering.py — Taste-map clustering tests (synthetic data only)
======================================================================
No warehouse, no API, no audio: synthetic 77-dim frames exercise the
contract validation, determinism, and the coarse-genre rule table.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.clustering import (
    VECTOR_77_COLUMNS,
    UNKNOWN_BUCKET,
    OTHER_BUCKET,
    map_genres_to_bucket,
    prepare_matrix,
    cluster_tracks,
    describe_clusters,
)


def _synthetic_frame(n_per_blob: int = 12, n_blobs: int = 3, seed: int = 7) -> pd.DataFrame:
    """Three well-separated blobs in 77-dim space (clearly clusterable)."""
    rng = np.random.default_rng(seed)
    rows = []
    for b in range(n_blobs):
        center = rng.normal(loc=b * 12.0, scale=1.0, size=len(VECTOR_77_COLUMNS))
        for i in range(n_per_blob):
            rows.append(center + rng.normal(0, 0.5, size=len(VECTOR_77_COLUMNS)))
    df = pd.DataFrame(rows, columns=VECTOR_77_COLUMNS)
    df["spotify_track_id"] = [f"synth_{i:03d}" for i in range(len(df))]
    buckets = ["Rock", "Punk & Emo", "Folk"]
    df["genre_bucket"] = [buckets[i % 3] for i in range(len(df))]
    df["primary_artist_name"] = [f"Artist {i % 5}" for i in range(len(df))]
    return df


class TestContract:
    def test_vector_columns_are_exactly_77(self):
        assert len(VECTOR_77_COLUMNS) == 77
        assert len(set(VECTOR_77_COLUMNS)) == 77  # no duplicates

    def test_prepare_matrix_shape_and_unit_norm(self):
        frame = _synthetic_frame()
        X = prepare_matrix(frame)
        assert X.shape == (len(frame), 77)
        norms = np.linalg.norm(X, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)  # L2-normalized rows


class TestClustering:
    def test_recovers_separated_blobs(self):
        frame = _synthetic_frame(n_per_blob=12, n_blobs=3)
        X = prepare_matrix(frame)
        labels, k, silhouette = cluster_tracks(X, k_range=(2, 6), random_state=42)
        assert k == 3                      # silhouette should find the 3 blobs
        assert silhouette > 0.5            # clearly separated
        assert len(labels) == len(frame)

    def test_deterministic_same_seed(self):
        frame = _synthetic_frame()
        X = prepare_matrix(frame)
        labels_a, k_a, _ = cluster_tracks(X, random_state=42)
        labels_b, k_b, _ = cluster_tracks(X, random_state=42)
        assert k_a == k_b
        assert np.array_equal(labels_a, labels_b)  # SPEC P1 acceptance

    def test_too_few_tracks_raises(self):
        X = prepare_matrix(_synthetic_frame(n_per_blob=1, n_blobs=2))
        with pytest.raises(ValueError, match="at least"):
            cluster_tracks(X, k_range=(3, 9))

    def test_describe_clusters_dominant_genre_skips_unknown(self):
        frame = _synthetic_frame(n_per_blob=4, n_blobs=1)
        frame["cluster_id"] = 0
        frame["genre_bucket"] = [UNKNOWN_BUCKET, UNKNOWN_BUCKET, "Rock", "Rock"]
        summary = describe_clusters(frame)
        assert summary.iloc[0]["dominant_genre"] == "Rock"
        assert summary.iloc[0]["n_tracks"] == 4

    def test_acoustic_labels_differentiate_loud_fast_from_quiet_slow(self):
        # Two clusters identical on everything except rms_mean and tempo_bpm:
        # labels must come from exactly those dims, in opposite directions.
        frame = _synthetic_frame(n_per_blob=6, n_blobs=1, seed=3)
        frame = pd.concat([frame, frame], ignore_index=True)
        frame["spotify_track_id"] = [f"t{i}" for i in range(len(frame))]
        frame["cluster_id"] = [0] * 6 + [1] * 6
        for col in ("rms_mean", "tempo_bpm"):
            frame.loc[frame["cluster_id"] == 0, col] = 10.0
            frame.loc[frame["cluster_id"] == 1, col] = -10.0
        # flatten every other characterization dim so rms/tempo dominate
        for col in ("harmonic_ratio", "spectral_centroid_mean", "zcr_mean",
                    "onset_strength_mean"):
            frame[col] = 1.0

        summary = describe_clusters(frame)
        label_0 = summary.loc[summary["cluster_id"] == 0, "acoustic_label"].iloc[0]
        label_1 = summary.loc[summary["cluster_id"] == 1, "acoustic_label"].iloc[0]
        assert set(label_0.split(" · ")) == {"Loud", "Fast"}
        assert set(label_1.split(" · ")) == {"Quiet", "Slow"}


class TestGenreMapping:
    @pytest.mark.parametrize("genres,expected", [
        ("pop punk", "Punk & Emo"),            # specific beats generic Pop
        ("folk pop", "Folk"),                  # Folk outranks Pop
        ("glam metal", "Metal"),
        ("alternative rock", "Indie & Alt"),   # Indie & Alt outranks Rock
        ("madchester", "Indie & Alt"),
        ("blues rock", "Blues"),               # Blues outranks Rock
        ("classic rock", "Rock"),
        ("opera, classical crossover", "Classical"),
        ("hip hop", "Hip-Hop"),
        ("post-grunge", "Punk & Emo"),         # grunge family
        ("egg punk", "Punk & Emo"),
        ("zydeco", OTHER_BUCKET),              # real tag, no rule
        ("", UNKNOWN_BUCKET),
        (None, UNKNOWN_BUCKET),
        ("   ", UNKNOWN_BUCKET),
    ])
    def test_bucket_rules(self, genres, expected):
        assert map_genres_to_bucket(genres) == expected

    def test_first_matching_rule_priority_across_tags(self):
        # Artist tagged both rock AND metal → Metal (higher-priority rule)
        assert map_genres_to_bucket("hard rock, heavy metal") == "Metal"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
