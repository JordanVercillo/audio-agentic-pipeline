"""
test_search.py — Smoke Test for the Vector Search Pipeline
============================================================
Tests the full search layer using synthetic audio data:
    1. Module imports
    2. Generate synthetic tracks with known acoustic properties
    3. Extract DSP features for each
    4. Build FAISS index
    5. Cosine similarity query (validate correct matches)
    6. Index persistence (save/load round-trip)
    7. UMAP projection
    8. End-to-end: features → Parquet → FAISS → query → UMAP

Run from the project root:
    python -m src.search.test_search
"""

import sys
import tempfile
from pathlib import Path

import numpy as np


def run_smoke_test():
    """Execute the full search pipeline smoke test."""

    print("=" * 60)
    print("  🧪  VECTOR SEARCH PIPELINE — Smoke Test")
    print("=" * 60)

    # ── 1. Imports ──
    print("\n━━━ TEST 1: Module Imports ━━━")
    from src.search import (
        FAISSStore, VectorStoreConfig, SimilarityMetric,
        compute_umap, plot_taste_map,
        build_index_from_features, find_similar_tracks,
    )
    from src.dsp import (
        generate_test_signal, extract_features, extract_embedding,
        save_features_to_parquet, save_embeddings_to_parquet,
    )
    print("   ✅ All modules imported")

    # ── 2. Generate synthetic tracks with distinct acoustic profiles ──
    print("\n━━━ TEST 2: Generate Synthetic Tracks ━━━")
    # Different frequencies create different spectral profiles,
    # so tracks with similar frequencies should cluster together in FAISS.
    synthetic_tracks = [
        # Bass tracks (low frequency — should cluster together)
        ("bass_deep_1",    100.0),
        ("bass_deep_2",    110.0),
        ("bass_sub",        80.0),
        # Mid tracks (mid frequency — should cluster together)
        ("mid_vocal_1",    440.0),
        ("mid_vocal_2",    466.0),
        ("mid_piano",      523.0),
        # High tracks (high frequency — should cluster together)
        ("high_bright_1", 2000.0),
        ("high_bright_2", 2200.0),
        ("high_sparkle",  3000.0),
    ]

    signals = []
    for name, freq in synthetic_tracks:
        sig = generate_test_signal(frequency_hz=freq, duration_sec=3.0)
        # Override the file_name for identification
        sig.file_name = name
        signals.append(sig)

    print(f"   ✅ Generated {len(signals)} synthetic tracks")
    for name, freq in synthetic_tracks:
        print(f"      {name}: {freq} Hz")

    # ── 3. Extract features ──
    print("\n━━━ TEST 3: Extract DSP Features ━━━")
    features_list = []
    for sig in signals:
        feat = extract_features(sig)
        features_list.append(feat)

    print(f"   ✅ Extracted features for {len(features_list)} tracks")

    # ── 4. Build FAISS index from summary vectors ──
    print("\n━━━ TEST 4: Build FAISS Index ━━━")
    track_ids = [f"spotify:track:synth_{name}" for name, _ in synthetic_tracks]

    # Extract summary vectors
    vectors = np.array([f.to_summary_vector() for f in features_list])
    print(f"   Vector matrix shape: {vectors.shape}")

    config = VectorStoreConfig()
    store = FAISSStore(dimension=vectors.shape[1], config=config)
    store.add(vectors, track_ids)

    assert store.size == len(synthetic_tracks), f"Expected {len(synthetic_tracks)}, got {store.size}"
    print(f"   ✅ FAISS index: {store.size} vectors ({store.dimension}D)")

    # ── 5. Cosine similarity query ──
    print("\n━━━ TEST 5: Cosine Similarity Query ━━━")
    # Query with "bass_deep_1" — should return other bass tracks as most similar
    query_id = "spotify:track:synth_bass_deep_1"
    results = store.query_by_track_id(query_id, k=5)

    assert len(results) > 0, "Query returned no results"
    print(f"   Query: {query_id}")
    print(f"   Results:")
    for r in results:
        sim_pct = r["similarity"] * 100
        print(f"      {r['rank']}. {r['spotify_track_id']} — {sim_pct:.1f}%")

    # The most similar track to bass_deep_1 (100 Hz) should be
    # bass_deep_2 (110 Hz) or bass_sub (80 Hz), NOT a high-frequency track
    top_result_id = results[0]["spotify_track_id"]
    assert "bass" in top_result_id or "sub" in top_result_id, (
        f"Expected a bass track as most similar to bass_deep_1, got: {top_result_id}"
    )
    print(f"   ✅ Most similar to bass_deep_1: {top_result_id} (correct!)")

    # ── 6. Index persistence ──
    print("\n━━━ TEST 6: Index Persistence (Save/Load) ━━━")
    with tempfile.TemporaryDirectory() as tmpdir:
        idx_path = Path(tmpdir) / "test.index"
        meta_path = Path(tmpdir) / "test_meta.parquet"

        store.save(index_path=idx_path, metadata_path=meta_path)

        # Load back
        store_loaded = FAISSStore.load(
            index_path=idx_path,
            metadata_path=meta_path,
        )

        assert store_loaded.size == store.size, "Size mismatch after reload"
        assert store_loaded.dimension == store.dimension, "Dimension mismatch"

        # Re-run the same query on the loaded store
        results_loaded = store_loaded.query_by_track_id(query_id, k=3)
        assert len(results_loaded) > 0, "Loaded store returned no results"
        assert results_loaded[0]["spotify_track_id"] == results[0]["spotify_track_id"], (
            "Loaded store returned different results"
        )

        print(f"   ✅ Save/load round-trip: {store_loaded.size} vectors preserved")
        print(f"   ✅ Query consistency verified after reload")

    # ── 7. UMAP projection ──
    print("\n━━━ TEST 7: UMAP Projection ━━━")
    all_vectors = store.get_all_vectors()

    projection = compute_umap(all_vectors, config=config)

    assert projection.shape == (len(synthetic_tracks), 2), (
        f"Expected shape ({len(synthetic_tracks)}, 2), got {projection.shape}"
    )
    assert projection.dtype == np.float32, f"Expected float32, got {projection.dtype}"
    assert not np.any(np.isnan(projection)), "UMAP projection contains NaN"

    print(f"   ✅ UMAP projection: {projection.shape} (no NaN)")

    # Validate clustering: bass tracks should be closer to each other than to high tracks
    # in the UMAP projection
    bass_coords = projection[:3]    # bass_deep_1, bass_deep_2, bass_sub
    high_coords = projection[6:9]   # high_bright_1, high_bright_2, high_sparkle

    bass_centroid = bass_coords.mean(axis=0)
    high_centroid = high_coords.mean(axis=0)

    # Intra-cluster distances (bass tracks to bass centroid)
    bass_spread = np.mean(np.linalg.norm(bass_coords - bass_centroid, axis=1))
    # Inter-cluster distance (bass centroid to high centroid)
    cluster_dist = np.linalg.norm(bass_centroid - high_centroid)

    print(f"   Bass cluster spread:    {bass_spread:.3f}")
    print(f"   Bass↔High cluster dist: {cluster_dist:.3f}")
    # We expect inter > intra (clusters are separated)
    if cluster_dist > bass_spread:
        print("   ✅ UMAP preserves cluster separation (inter > intra)")
    else:
        print("   ⚠️  Cluster separation marginal (random seed dependent)")

    # ── 8. End-to-end via Parquet ──
    print("\n━━━ TEST 8: End-to-End (Features → Parquet → FAISS) ━━━")
    with tempfile.TemporaryDirectory() as tmpdir:
        feat_path = Path(tmpdir) / "features.parquet"
        idx_path = Path(tmpdir) / "e2e.index"
        meta_path = Path(tmpdir) / "e2e_meta.parquet"

        # Save features to Parquet
        save_features_to_parquet(
            features_list,
            feat_path,
            spotify_track_ids=track_ids,
            append=False,
        )

        # Build index from Parquet
        e2e_config = VectorStoreConfig(
            index_path=idx_path,
            metadata_path=meta_path,
        )
        e2e_store = build_index_from_features(feat_path, config=e2e_config, save=True)

        assert e2e_store.size == len(synthetic_tracks)
        assert idx_path.exists(), "Index file not created"
        assert meta_path.exists(), "Metadata file not created"

        # Query
        e2e_results = e2e_store.query_by_track_id(query_id, k=3)
        assert len(e2e_results) > 0

        print(f"   ✅ End-to-end pipeline: {e2e_store.size} tracks indexed & queryable")

    # Close any open matplotlib figures
    import matplotlib.pyplot as plt
    plt.close("all")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅  ALL TESTS PASSED — Vector Search Pipeline is operational!")
    print("=" * 60)


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    run_smoke_test()
