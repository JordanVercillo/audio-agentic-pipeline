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
