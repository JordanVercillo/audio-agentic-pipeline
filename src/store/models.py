"""
models.py — SQLAlchemy schema for the shared feature cache (APP_SPEC Epic A).

Two tables, both keyed on the bridge key `spotify_track_id`:
    - track_features: one row per song (user-agnostic — songs, not people; D-7).
    - extraction_jobs: the async work queue; a cache miss becomes a job.

The full 82-column DSP contract lives in the JSON `features` column (portable
across SQLite + Postgres); three interpretable features are promoted to real
columns for querying without a JSON parse. Epic B adds a Postgres-only pgvector
`Vector(77)` column derived from `features` for similarity search.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import JSON

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrackFeatures(Base):
    __tablename__ = "track_features"

    spotify_track_id = Column(String, primary_key=True)
    features = Column(JSON, nullable=False)  # the full to_summary_dict (82 cols)
    # Promoted interpretable features (query without parsing JSON).
    tempo_bpm = Column(Float)
    rms_mean = Column(Float)
    spectral_centroid_mean = Column(Float)
    # Provenance.
    dsp_version = Column(String)
    extraction_source = Column(String)      # e.g. "youtube"
    spectrogram_uri = Column(String)        # path / GCS uri to the mel-spectrogram PNG
    extracted_at = Column(DateTime, default=utcnow)


class TrackMeta(Base):
    """Minimal metadata for the YouTube search query (set when a miss is enqueued)."""

    __tablename__ = "track_meta"

    spotify_track_id = Column(String, primary_key=True)
    track_name = Column(String)
    artist_names = Column(String)
    album_name = Column(String)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    spotify_track_id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|failed
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String)
    requested_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TrackPerceptual(Base):
    """A track's perceptual-v1 features (VISION_SPECS F1) — the derived layer."""

    __tablename__ = "track_perceptual"

    spotify_track_id = Column(String, primary_key=True)
    features = Column(JSON, nullable=False)   # {tempo, key, mode, …, valence_proxy}
    version = Column(String, nullable=False)  # e.g. "perceptual-v1"
    computed_at = Column(DateTime, default=utcnow)


class ClusterModel(Base):
    """A versioned clustering model (APP_SPEC Epic C) — enough state to assign
    new tracks online: the scaler stats + centroids in scaled space."""

    __tablename__ = "cluster_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)          # "song" | "artist"
    k = Column(Integer, nullable=False)
    silhouette = Column(Float)
    feature_cols = Column(JSON, nullable=False)    # ordered list of columns used
    scaler_mean = Column(JSON, nullable=False)     # per-column population mean
    scaler_std = Column(JSON, nullable=False)      # per-column population std
    centroids = Column(JSON, nullable=False)       # k × d, in scaled+normalized space
    labels = Column(JSON, nullable=False)          # {"0": "Loud · Fast", ...}
    trained_at = Column(DateTime, default=utcnow)


class TrackCluster(Base):
    """A track's cluster assignment + 2-D map coordinates (bridge-key keyed)."""

    __tablename__ = "track_clusters"

    spotify_track_id = Column(String, primary_key=True)
    model_id = Column(Integer, nullable=False)
    cluster_id = Column(Integer, nullable=False)
    map_x = Column(Float)   # 2-D embedding (UMAP/PCA) — nullable for online assigns
    map_y = Column(Float)


class ArtistProfile(Base):
    """An artist's acoustic bucket, derived from their cached tracks' centroid.

    Keyed by primary-artist NAME for now (the cache meta stores names; Spotify
    artist ids can replace the key later without changing the shape)."""

    __tablename__ = "artist_profiles"

    artist_key = Column(String, primary_key=True)
    track_count = Column(Integer, nullable=False, default=0)
    model_id = Column(Integer)
    cluster_id = Column(Integer)
