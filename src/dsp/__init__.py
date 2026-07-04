"""
src.dsp — Local DSP Feature Extraction Pipeline
================================================
Replaces Spotify's deprecated /audio-features endpoint with local
acoustic intelligence extracted from user-provided audio files.

Quick Start:
    >>> from src.dsp import load_audio, extract_features, extract_embedding
    >>> signal = load_audio("path/to/track.mp3")
    >>> features = extract_features(signal)
    >>> embedding = extract_embedding(signal)

    # Phase 2 — batch extraction from downloaded MP3s:
    >>> from src.dsp import extract_features_for_collection
    >>> features_df = extract_features_for_collection()  # reads data/raw_audio/

Public API:
    - load_audio()              Load & normalize a single audio file
    - load_audio_batch()        Load all audio files from a directory
    - generate_test_signal()    Create a synthetic sine wave for testing
    - extract_features()        Full DSP pipeline → TrackFeatures
    - extract_embedding()       Dense vector embedding (PANNs or summary)
    - save_features_to_parquet()   Persist features → Parquet
    - save_embeddings_to_parquet() Persist embeddings → Parquet

Collection Extraction (Phase 2 — Real Audio):
    - extract_features_for_collection()  Batch extract 77D features from data/raw_audio/
    - extract_features_for_track()       Extract features for a single MP3 path
    - load_features_parquet()      Read features back from Parquet
    - load_embeddings_as_matrix()  Read embeddings as numpy matrix

Data Classes:
    - DSPConfig          Runtime DSP parameter overrides
    - AudioSignal        Standardized audio container
    - TrackFeatures      Complete feature extraction result
    - AudioEmbedding     Dense vector embedding container
"""

# Configuration
# Audio I/O
from .audio_loader import (
    AudioSignal,
    generate_test_signal,
    load_audio,
    load_audio_batch,
)

# Collection Extraction (Phase 2)
from .collection_extractor import (
    extract_features_for_collection,
    extract_features_for_track,
)
from .config import SAMPLE_RATE, DSPConfig, FeatureGroup

# Embedding Extraction
from .embedding_extractor import (
    AudioEmbedding,
    extract_embedding,
    extract_embedding_panns,
    extract_embedding_summary,
)

# Feature Extraction
from .feature_extractor import TrackFeatures, extract_features

# Serialization
from .serializer import (
    load_embeddings_as_matrix,
    load_features_parquet,
    save_embeddings_to_parquet,
    save_features_to_parquet,
)

__all__ = [
    # Config
    "DSPConfig", "FeatureGroup", "SAMPLE_RATE",
    # Audio I/O
    "AudioSignal", "load_audio", "load_audio_batch", "generate_test_signal",
    # Features
    "TrackFeatures", "extract_features",
    # Collection Extraction (Phase 2)
    "extract_features_for_collection", "extract_features_for_track",
    # Embeddings
    "AudioEmbedding", "extract_embedding",
    "extract_embedding_panns", "extract_embedding_summary",
    # Serialization
    "save_features_to_parquet", "save_embeddings_to_parquet",
    "load_features_parquet", "load_embeddings_as_matrix",
]
