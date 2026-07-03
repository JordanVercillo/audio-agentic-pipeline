"""
test_dsp.py — Smoke Test for the DSP Feature Extraction Pipeline
================================================================
Generates a synthetic 440Hz sine wave and runs it through the entire
pipeline to validate:
    1. AudioSignal creation & metadata
    2. Feature extraction (all groups)
    3. Summary vector dimensionality (77D)
    4. Parquet serialization round-trip
    5. Key estimation sanity check

Run from the project root:
    python -m src.dsp.test_dsp
"""

import sys
import tempfile
from pathlib import Path

import numpy as np


def run_smoke_test():
    """Execute the full DSP pipeline smoke test."""

    print("=" * 60)
    print("  🧪  DSP PIPELINE — Smoke Test")
    print("=" * 60)

    # ── 1. Generate synthetic signal ──
    print("\n━━━ TEST 1: Audio Signal Generation ━━━")
    from src.dsp import generate_test_signal, DSPConfig, SAMPLE_RATE

    signal = generate_test_signal(frequency_hz=440.0, duration_sec=5.0)

    assert signal.sr == SAMPLE_RATE, f"Expected sr={SAMPLE_RATE}, got {signal.sr}"
    assert signal.duration_sec == 5.0, f"Expected 5.0s, got {signal.duration_sec}"
    assert signal.n_samples == SAMPLE_RATE * 5, f"Sample count mismatch"
    assert signal.waveform.dtype == np.float32, f"Expected float32, got {signal.waveform.dtype}"
    assert np.max(np.abs(signal.waveform)) <= 1.0, "Waveform not normalized to [-1, 1]"

    print(f"   ✅ Signal: {signal.file_name}")
    print(f"      sr={signal.sr} Hz | {signal.duration_sec}s | {signal.n_samples} samples")
    print(f"      Peak amplitude: {np.max(np.abs(signal.waveform)):.4f}")

    # ── 2. Feature extraction ──
    print("\n━━━ TEST 2: Feature Extraction ━━━")
    from src.dsp import extract_features

    features = extract_features(signal)

    # Validate rhythm
    assert features.tempo_bpm >= 0, "Tempo should be non-negative"
    assert features.beat_count >= 0, "Beat count should be non-negative"
    print(f"   Tempo:        {features.tempo_bpm:.1f} BPM")
    print(f"   Beats:        {features.beat_count} ({features.beats_per_sec:.2f}/sec)")

    # Validate energy
    assert features.rms_mean > 0, "RMS should be positive for a non-silent signal"
    print(f"   RMS Energy:   mean={features.rms_mean:.4f}, std={features.rms_std:.4f}")
    print(f"   ZCR:          mean={features.zcr_mean:.4f}")

    # Validate MFCCs
    assert features.mfcc_means is not None, "MFCCs should be computed"
    assert features.mfcc_means.shape == (13,), f"Expected 13 MFCCs, got {features.mfcc_means.shape}"
    print(f"   MFCCs:        {features.mfcc_means.shape[0]} coefficients ✅")

    # Validate chroma
    assert features.chroma_means is not None, "Chroma should be computed"
    assert features.chroma_means.shape == (12,), f"Expected 12 chroma bins, got shape {features.chroma_means.shape}"
    print(f"   Chroma:       {features.chroma_means.shape[0]} pitch classes ✅")

    # Validate mel spectrogram
    assert features.mel_spectrogram_db is not None, "Mel spec should be computed"
    n_mels, t_frames = features.mel_spectrogram_db.shape
    expected_mels = 128
    assert n_mels == expected_mels, f"Expected {expected_mels} mel bands, got {n_mels}"
    print(f"   Mel Spec:     ({n_mels}, {t_frames}) — {n_mels} mels × {t_frames} frames ✅")

    # Validate harmonic ratio
    assert 0.0 <= features.harmonic_ratio <= 1.0, f"Harmonic ratio out of range: {features.harmonic_ratio}"
    print(f"   Harmonic:     {features.harmonic_ratio:.4f} (acousticness proxy)")

    # Validate spectral
    print(f"   Centroid:     {features.spectral_centroid_mean:.1f} Hz")
    print(f"   Rolloff:      {features.spectral_rolloff_mean:.1f} Hz")

    # Validate key/mode
    pitch_classes = ["C", "C#", "D", "D#", "E", "F",
                     "F#", "G", "G#", "A", "A#", "B"]
    key_name = pitch_classes[features.estimated_key] if 0 <= features.estimated_key < 12 else "?"
    print(f"   Key:          {key_name} {features.estimated_mode}")

    print("   ✅ All features extracted successfully!")

    # ── 3. Summary vector ──
    print("\n━━━ TEST 3: Summary Vector ━━━")
    vec = features.to_summary_vector()
    assert vec.shape == (77,), f"Expected 77D summary vector, got {vec.shape}"
    assert vec.dtype == np.float32, f"Expected float32, got {vec.dtype}"
    assert not np.any(np.isnan(vec)), "Summary vector contains NaN values"
    print(f"   ✅ Summary vector: {vec.shape} ({vec.dtype}), no NaNs")

    # ── 4. Embedding (summary fallback) ──
    print("\n━━━ TEST 4: Embedding Extraction (Summary Fallback) ━━━")
    from src.dsp import extract_embedding

    emb = extract_embedding(signal, method="summary")
    assert emb.embedding_dim == 77, f"Expected 77D, got {emb.embedding_dim}"
    assert emb.model_name == "dsp_summary_v1"
    print(f"   ✅ Embedding: {emb.embedding_dim}D via {emb.model_name}")

    # ── 5. Parquet serialization round-trip ──
    print("\n━━━ TEST 5: Parquet Serialization Round-Trip ━━━")
    from src.dsp import save_features_to_parquet, load_features_parquet

    with tempfile.TemporaryDirectory() as tmpdir:
        parquet_path = Path(tmpdir) / "test_features.parquet"

        # Save
        save_features_to_parquet(
            [features],
            parquet_path,
            spotify_track_ids=["spotify:track:test_440hz"],
            append=False,
        )

        # Load back
        df = load_features_parquet(parquet_path)

        assert len(df) == 1, f"Expected 1 row, got {len(df)}"
        assert "spotify_track_id" in df.columns, "Missing spotify_track_id bridge key"
        assert df["spotify_track_id"].iloc[0] == "spotify:track:test_440hz"

        # Verify numeric precision preserved
        assert df["tempo_bpm"].dtype in (np.float32, np.float64), "Tempo dtype not float"
        assert abs(df["tempo_bpm"].iloc[0] - features.tempo_bpm) < 0.01, "Tempo value mismatch"

        print(f"   ✅ Parquet round-trip: {len(df)} row, {len(df.columns)} columns")
        print(f"      Bridge key: {df['spotify_track_id'].iloc[0]}")

    # ── 6. to_summary_dict ──
    print("\n━━━ TEST 6: Summary Dict ━━━")
    d = features.to_summary_dict()
    assert isinstance(d, dict), "to_summary_dict should return a dict"
    assert "mfcc_mean_0" in d, "Should have expanded MFCC columns"
    assert "chroma_mean_A" in d, "Should have expanded chroma columns"
    print(f"   ✅ Summary dict: {len(d)} fields")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅  ALL TESTS PASSED — DSP Pipeline is operational!")
    print("=" * 60)

    return features


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    run_smoke_test()
