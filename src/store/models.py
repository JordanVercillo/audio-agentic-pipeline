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
    # Estimated meter (beats per bar) — a promoted column (F-v2), NOT in the
    # features dict, so the frozen vector + 82-col warehouse contract are untouched.
    time_signature = Column(Integer)
    # Within-track loudness curve (F-v2): a downsampled dBFS time series for the
    # deep-dive chart. Display data — deliberately OUT of `features` so it never
    # touches the 77-dim vector, the 82-col contract, or the perceptual transform.
    loudness_curve = Column(JSON)           # list[float] (dBFS) or null
    beat_times = Column(JSON)               # list[float] (seconds) — the beat grid (F-v2c)
    sections = Column(JSON)                 # [{start,end,label,…}] — detected structure (F-v3)
    # Provenance.
    dsp_version = Column(String)
    extraction_source = Column(String)      # e.g. "youtube"
    spectrogram_uri = Column(String)        # path / GCS uri to the mel-spectrogram PNG
    # O2 (D-22): the acquisition match's heuristic confidence [0,1] — recorded
    # per extraction for wrong-version analysis. Display/audit data, never a
    # feature and never a gate. NULL for pre-O2 rows.
    match_confidence = Column(Float)
    extracted_at = Column(DateTime, default=utcnow)


class TrackMeta(Base):
    """Minimal metadata for the YouTube search query (set when a miss is enqueued)."""

    __tablename__ = "track_meta"

    spotify_track_id = Column(String, primary_key=True)
    track_name = Column(String)
    artist_names = Column(String)
    album_name = Column(String)
    # Spotify popularity 0–100 at last sight — deprecated-NOT-removed upstream
    # (journal #20). Fetched CONTEXT: display/analysis only, never an ML input;
    # nullable because the field may vanish upstream any day.
    popularity = Column(Integer)
    # Track length at last sight (fetched context) — the dedup duration window
    # (Epic O / D-28). Nullable; forward-only migration like popularity.
    duration_ms = Column(Integer)
    # Near-duplicate FLAG (D-28): the spotify_track_id of this track's canonical
    # twin, or NULL. A SOFT reference for display/analysis + the audit — NOT a
    # primary key, NOT a foreign key, and NOTHING joins on it. The bridge key
    # stays spotify_track_id; dedup never mints or merges an id.
    duplicate_of = Column(String)
    # Display context, captured from the top-tracks fetch that already carries
    # them (P3.1/D-36) — art for the library/guest-dashboard, the primary
    # artist's Spotify id to harden the name-keyed artist join. Nullable,
    # forward-only migration like popularity.
    album_image_url = Column(String)
    primary_artist_id = Column(String)


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


class WorkerHeartbeat(Base):
    """Liveness beacon: the extraction worker upserts its row once per poll
    loop, so the app-verify audit can tell "worker alive" from "queue stuck"
    (a queue with no consumer fails silently — new visitors' tracks would
    show "analyzing…" forever)."""

    __tablename__ = "worker_heartbeats"

    worker_name = Column(String, primary_key=True)  # e.g. "extraction-worker"
    pid = Column(Integer)
    interval_seconds = Column(Integer)              # the worker's poll interval
    beat_at = Column(DateTime, default=utcnow)


class ArtistProfile(Base):
    """An artist's acoustic bucket, derived from their cached tracks' centroid.

    Keyed by primary-artist NAME for now (the cache meta stores names; Spotify
    artist ids can replace the key later without changing the shape)."""

    __tablename__ = "artist_profiles"

    artist_key = Column(String, primary_key=True)
    track_count = Column(Integer, nullable=False, default=0)
    model_id = Column(Integer)
    cluster_id = Column(Integer)


class ArtistMeta(Base):
    """Fetched artist metadata — the serving path for genres/images/popularity
    (P3.1/D-36). Populated FREE at dashboard build (the top-artists fetch
    already carries all of it and used to throw it away); `dim_artists` is a
    one-time seed, not a serving path. Every field except id/name is on
    Spotify's deprecated/removed lists → nullable, absent-safe, and the stored
    copy is the system of record (genres can't be un-shipped)."""

    __tablename__ = "artist_meta"

    artist_id = Column(String, primary_key=True)     # Spotify artist id
    artist_name = Column(String)
    genres = Column(String)                          # comma-joined; may be ""
    followers = Column(Integer)
    popularity = Column(Integer)                     # fetched context (P3.0a)
    image_url = Column(String)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ChatLog(Base):
    """One LLM-surface turn (/ask · /classify · /chat), logged for the REVIEW
    READER (D-47): a row must let a human grade accuracy without re-running —
    the question, the FULL grounding actually sent, the raw + parsed output, the
    source, and cost. `chat_session_id` is a fresh uuid4 minted per chat — NEVER
    the auth sid (that's a live credential). Disclosed on /privacy; 90-day
    retention (owner, 2026-07-17). New table → create_all builds it; no
    _ADDED_COLUMNS entry needed (journal #18)."""

    __tablename__ = "chat_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_session_id = Column(String, nullable=False)   # uuid4, minted per chat — not the auth sid
    turn_index = Column(Integer, nullable=False, default=0)
    mode = Column(String, nullable=False)              # adhoc | story | profile
    prompt_version = Column(String)                    # "rtcros-v1" — attributes scores to a contract
    user_question = Column(String)                     # raw, untrusted text
    rendered_context = Column(String)                  # the FULL grounding actually sent
    raw_model_output = Column(String)                  # pre-parse; NULL on fallback turns
    parsed_answer = Column(String)                     # what the visitor saw (fallback text too)
    cited_entities = Column(JSON)                      # the parsed cited[] array
    source = Column(String, nullable=False)            # llm | fallback | none
    model = Column(String)                             # "ollama:gemma4:12b" | NULL
    ctx_tokens = Column(Integer)                       # Ollama prompt_eval_count (real, when available)
    output_tokens = Column(Integer)                    # Ollama eval_count
    latency_ms = Column(Integer)                       # wall clock — covers fallback turns too
    error = Column(String)                             # why a turn degraded (timeout | parse | verify)
    created_at = Column(DateTime, default=utcnow)


class ChatLabel(Base):
    """A human grade of a ChatLog row (D-47 flywheel). rubric-v1: the anchors
    that become the K5 adapter labels + new golden cases. Soft `log_id`
    reference (no FK — the duplicate_of precedent)."""

    __tablename__ = "chat_labels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(Integer, nullable=False)           # soft ref → chat_log.id
    rubric_version = Column(String, nullable=False, default="rubric-v1")
    accuracy = Column(Integer)                         # 0-2, vs rendered_context ONLY
    citation_fidelity = Column(Integer)                # 0-2
    invention = Column(Integer)                        # 0/1 — the safety bit
    usefulness = Column(Integer)                       # 0-2
    verdict = Column(String)                           # good | fixable-prompt | fixable-context | bad
    missing_fact = Column(String)                      # what the context lacked — the RAG seed
    golden_proposal = Column(JSON)                     # {kind, question, must_cite[]} | NULL
    grader = Column(String)                            # "jordan"
    notes = Column(String)
    graded_at = Column(DateTime, default=utcnow)
