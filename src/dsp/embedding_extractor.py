"""
embedding_extractor.py — Deep Audio Embeddings (PANNs)
======================================================
For similarity search, raw DSP features are noisy and high-dimensional.
Pre-trained neural audio embeddings compress a full audio signal into a
semantically meaningful dense vector (512D–2048D) where similar-sounding
tracks cluster together in embedding space.

Strategy (from 02_audio_dsp_architect.md):
    - Primary: PANNs Cnn14 (2048D) — best for general audio patterns
    - Fallback: Summary vector from feature_extractor (77D) — no GPU needed

The PANNs model (Kong et al., 2020) was trained on AudioSet (2M clips,
527 classes). Its penultimate layer produces a 2048D embedding that
captures genre, instrumentation, mood, and production style — exactly
what we need for music similarity without relying on Spotify.

Reference: 02_audio_dsp_architect.md — "Deep Audio Embeddings" section
"""

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np

from .audio_loader import AudioSignal
from .config import DSPConfig
from .feature_extractor import TrackFeatures, extract_features

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA STRUCTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AudioEmbedding:
    """
    Container for a track's dense embedding vector.

    Attributes:
        file_name:      Source audio file stem.
        file_path:      Full path to source file.
        embedding:      Dense vector (float32). Shape depends on model used.
        embedding_dim:  Dimensionality of the embedding.
        model_name:     Which model produced this embedding.
        duration_sec:   Duration of the source audio.
    """
    file_name: str
    file_path: str
    embedding: np.ndarray
    embedding_dim: int
    model_name: str
    duration_sec: float


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PANNs EMBEDDING EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_embedding_panns(
    signal: AudioSignal,
    model_path: Optional[Union[str, Path]] = None,
) -> AudioEmbedding:
    """
    Extract a 2048D embedding using PANNs Cnn14.

    The panns_inference package handles model loading and checkpoint
    management. On first use, it downloads the Cnn14 weights (~300MB)
    and caches them locally.

    Input requirements (handled automatically):
        - Sample rate: 32000 Hz (PANNs native — we resample from 22050)
        - Mono channel
        - Float32 waveform

    Args:
        signal:     AudioSignal from audio_loader.
        model_path: Optional path to a pre-downloaded checkpoint.

    Returns:
        AudioEmbedding with 2048D vector.

    Raises:
        ImportError: If panns_inference is not installed.
    """
    try:
        from panns_inference import AudioTagging
    except ImportError:
        raise ImportError(
            "panns_inference is required for deep embeddings.\n"
            "Install: pip install panns-inference\n"
            "Or use extract_embedding_summary() as a lightweight fallback."
        ) from None

    # PANNs expects 32000 Hz — resample from our canonical 22050 Hz
    import librosa
    y_32k = librosa.resample(signal.waveform, orig_sr=signal.sr, target_sr=32000)

    # AudioTagging loads Cnn14 by default; model_path overrides checkpoint location
    kwargs = {}
    if model_path:
        kwargs["checkpoint_path"] = str(model_path)

    at = AudioTagging(**kwargs)

    # PANNs expects shape (batch, samples) — add batch dimension
    audio_input = y_32k[np.newaxis, :]

    # Forward pass: returns (clipwise_output, embedding)
    # clipwise_output = class probabilities for 527 AudioSet categories
    # embedding = 2048D penultimate layer activation (what we want)
    _, embedding = at.inference(audio_input)

    # Squeeze batch dimension: (1, 2048) → (2048,)
    embedding_vector = embedding[0].astype(np.float32)

    return AudioEmbedding(
        file_name=signal.file_name,
        file_path=signal.file_path,
        embedding=embedding_vector,
        embedding_dim=len(embedding_vector),
        model_name="panns_cnn14",
        duration_sec=signal.duration_sec,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIGHTWEIGHT FALLBACK: SUMMARY VECTOR EMBEDDING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_embedding_summary(
    signal: AudioSignal,
    config: Optional[DSPConfig] = None,
    features: Optional[TrackFeatures] = None,
) -> AudioEmbedding:
    """
    Fallback embedding: use the 77D summary vector from feature_extractor.

    This doesn't require any neural network or GPU — it aggregates the
    hand-crafted DSP features (MFCCs, chroma, spectral shape, rhythm)
    into a single vector suitable for cosine similarity search.

    While less semantically rich than PANNs (77D vs 2048D), it captures
    the core acoustic dimensions and works well for small-to-medium
    collections (< 10K tracks).

    Args:
        signal:   AudioSignal from audio_loader.
        config:   Optional DSPConfig override.
        features: Pre-computed TrackFeatures (if you already ran extract_features).
                  If None, features are computed fresh.

    Returns:
        AudioEmbedding with 77D summary vector.
    """
    if features is None:
        features = extract_features(signal, config=config)

    vec = features.to_summary_vector()

    return AudioEmbedding(
        file_name=signal.file_name,
        file_path=signal.file_path,
        embedding=vec,
        embedding_dim=len(vec),
        model_name="dsp_summary_v1",
        duration_sec=signal.duration_sec,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UNIFIED INTERFACE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_embedding(
    signal: AudioSignal,
    method: str = "auto",
    config: Optional[DSPConfig] = None,
) -> AudioEmbedding:
    """
    Extract an audio embedding using the best available method.

    Args:
        signal: AudioSignal from audio_loader.
        method: Embedding strategy:
            - "auto":    Try PANNs first, fall back to summary vector.
            - "panns":   Force PANNs (raises ImportError if not installed).
            - "summary": Force lightweight summary vector (no dependencies).
        config: Optional DSPConfig override (used by summary method).

    Returns:
        AudioEmbedding from the selected method.
    """
    if method == "panns":
        return extract_embedding_panns(signal)

    if method == "summary":
        return extract_embedding_summary(signal, config=config)

    # Auto mode: try PANNs, gracefully fall back
    if method == "auto":
        try:
            return extract_embedding_panns(signal)
        except ImportError:
            warnings.warn(
                "PANNs not available — using DSP summary vector (77D) as fallback. "
                "Install panns-inference for richer 2048D embeddings.",
                UserWarning, stacklevel=2,
            )
            return extract_embedding_summary(signal, config=config)

    raise ValueError(f"Unknown embedding method: '{method}'. Use 'auto', 'panns', or 'summary'.")
