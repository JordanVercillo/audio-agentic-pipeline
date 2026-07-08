"""
cache.py — FeatureCache, the shared track-keyed feature store (APP_SPEC Epic A).

The serving/cache layer (D-12): low-latency point lookups by `spotify_track_id`,
plus the async extraction queue. Portable across SQLite (dev/tests, the default)
and Postgres (prod, via DATABASE_URL). Every method is keyed on the bridge key.

Worker loop:
    tid = cache.claim_next()          # queued → running (atomic)
    ... extract features + spectrogram ...
    cache.upsert(tid, features, ...)  # writes the row AND marks the job done
    # on failure: cache.fail(tid, error)
"""

from __future__ import annotations

import math
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from .models import Base, ExtractionJob, TrackFeatures, TrackMeta, utcnow

# Feature columns used for "songs like this" (whatever's present rides along).
_SIMILARITY_COLS = [
    "tempo_bpm", "rms_mean", "zcr_mean", "spectral_centroid_mean",
    "spectral_rolloff_mean", "spectral_bandwidth_mean", "harmonic_ratio",
    "onset_strength_mean", *(f"mfcc_mean_{i}" for i in range(5)),
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_SQLITE = f"sqlite:///{_PROJECT_ROOT / 'data' / 'feature_cache.db'}"

_PROMOTED = ("tempo_bpm", "rms_mean", "spectral_centroid_mean")
JOB_QUEUED, JOB_RUNNING, JOB_DONE, JOB_FAILED = "queued", "running", "done", "failed"


def database_url() -> str:
    """Postgres in prod (``DATABASE_URL``), or a local SQLite file for dev/tests."""
    return os.environ.get("DATABASE_URL", _DEFAULT_SQLITE)


def _f(v: Any) -> Optional[float]:
    return None if v is None else float(v)


class FeatureCache:
    def __init__(self, url: Optional[str] = None) -> None:
        url = url or database_url()
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, future=True)
        if url.startswith("sqlite"):
            # WAL: the webapp and the extraction worker are two PROCESSES sharing
            # this file — WAL allows a reader and the writer to coexist, and
            # busy_timeout waits out short write locks instead of erroring (D-12).
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        """Release pooled connections — required before file-level operations on
        the SQLite db (e.g. restore), which Windows blocks while a handle is open."""
        self.engine.dispose()

    # ── reads ──────────────────────────────────────────────────────────────
    def get(self, track_ids: list[str]) -> dict[str, dict]:
        """Cached feature dicts for the given ids (only those present)."""
        if not track_ids:
            return {}
        with self._Session() as s:
            rows = s.execute(
                select(TrackFeatures).where(
                    TrackFeatures.spotify_track_id.in_(track_ids))
            ).scalars().all()
        return {r.spotify_track_id: r.features for r in rows}

    def all_features(self) -> dict[str, dict]:
        """Every cached track's features — the clustering population (Epic C)."""
        with self._Session() as s:
            rows = s.execute(select(TrackFeatures)).scalars().all()
        return {r.spotify_track_id: r.features for r in rows}

    def all_meta(self) -> dict[str, dict]:
        """Every track's metadata, keyed by bridge key."""
        with self._Session() as s:
            rows = s.execute(select(TrackMeta)).scalars().all()
        return {m.spotify_track_id: {
            "track_name": m.track_name, "artist_names": m.artist_names,
        } for m in rows}

    def cached_ids(self, track_ids: list[str]) -> set[str]:
        if not track_ids:
            return set()
        with self._Session() as s:
            rows = s.execute(
                select(TrackFeatures.spotify_track_id).where(
                    TrackFeatures.spotify_track_id.in_(track_ids))
            ).scalars().all()
        return set(rows)

    def missing(self, track_ids: list[str]) -> list[str]:
        """Uncached ids, deduped, in input order."""
        cached = self.cached_ids(track_ids)
        seen: set[str] = set()
        out: list[str] = []
        for t in track_ids:
            if t not in cached and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    # ── writes ─────────────────────────────────────────────────────────────
    def upsert(self, track_id: str, features: dict, *, spectrogram_uri: Optional[str] = None,
               source: str = "youtube", dsp_version: Optional[str] = None) -> None:
        """Store a song's features (idempotent) and mark any pending job done."""
        with self._Session() as s:
            s.merge(TrackFeatures(
                spotify_track_id=track_id, features=features,
                tempo_bpm=_f(features.get("tempo_bpm")),
                rms_mean=_f(features.get("rms_mean")),
                spectral_centroid_mean=_f(features.get("spectral_centroid_mean")),
                spectrogram_uri=spectrogram_uri, extraction_source=source,
                dsp_version=dsp_version, extracted_at=utcnow()))
            job = s.get(ExtractionJob, track_id)
            if job is not None:
                job.status = JOB_DONE
                job.last_error = None
            s.commit()

    # ── track metadata (for the worker's YouTube query) ─────────────────────
    def remember_meta(self, items: list[dict]) -> None:
        """Upsert minimal metadata (name/artist) so the worker can search for the audio."""
        if not items:
            return
        with self._Session() as s:
            for it in items:
                tid = it.get("spotify_track_id") or it.get("id")
                if not tid:
                    continue
                s.merge(TrackMeta(
                    spotify_track_id=tid,
                    track_name=it.get("track_name") or it.get("name"),
                    artist_names=it.get("artist_names") or it.get("artist"),
                    album_name=it.get("album_name")))
            s.commit()

    def get_meta(self, track_id: str) -> Optional[dict]:
        with self._Session() as s:
            m = s.get(TrackMeta, track_id)
            if m is None:
                return None
            return {"spotify_track_id": m.spotify_track_id, "track_name": m.track_name,
                    "artist_names": m.artist_names, "album_name": m.album_name}

    # ── queue ──────────────────────────────────────────────────────────────
    def enqueue(self, track_ids: list[str]) -> list[str]:
        """Queue extraction for uncached ids without a live job. Returns the newly queued."""
        ids = self.missing(track_ids)
        if not ids:
            return []
        with self._Session() as s:
            live = set(s.execute(
                select(ExtractionJob.spotify_track_id).where(
                    ExtractionJob.spotify_track_id.in_(ids),
                    ExtractionJob.status.in_([JOB_QUEUED, JOB_RUNNING]))
            ).scalars().all())
            new = [t for t in ids if t not in live]
            for t in new:
                s.merge(ExtractionJob(spotify_track_id=t, status=JOB_QUEUED, attempts=0))
            s.commit()
        return new

    def claim_next(self) -> Optional[str]:
        """Atomically take the oldest queued job → running. None if the queue is empty.

        Postgres note: concurrent workers should add ``.with_for_update(skip_locked=True)``
        (added with the deploy slice); SQLite is single-writer, so this is safe as-is.
        """
        with self._Session() as s:
            job = s.execute(
                select(ExtractionJob).where(ExtractionJob.status == JOB_QUEUED)
                .order_by(ExtractionJob.requested_at).limit(1)
            ).scalars().first()
            if job is None:
                return None
            job.status = JOB_RUNNING
            job.attempts += 1
            s.commit()
            return job.spotify_track_id

    def fail(self, track_id: str, error: str = "") -> None:
        with self._Session() as s:
            job = s.get(ExtractionJob, track_id)
            if job is not None:
                job.status = JOB_FAILED
                job.last_error = (error or "")[:500]
                s.commit()

    def similar(self, track_id: str, k: int = 6) -> list[tuple[str, float]]:
        """Nearest cached tracks by z-scored acoustic distance → [(id, distance)].

        Portable (works on SQLite + Postgres). Loads the cached population and
        computes distance in Python — fine at pilot scale; prod swaps in pgvector
        (`ORDER BY vector <-> :target`) over the Epic-B Vector(77) column.
        """
        with self._Session() as s:
            target = s.get(TrackFeatures, track_id)
            if target is None:
                return []
            pop = s.execute(select(TrackFeatures)).scalars().all()
        if len(pop) < 2:
            return []

        cols = [c for c in _SIMILARITY_COLS
                if any((r.features or {}).get(c) is not None for r in pop)]
        if not cols:
            return []
        means = {c: statistics.fmean(float((r.features or {}).get(c) or 0.0) for r in pop) for c in cols}
        stds = {c: (statistics.pstdev(float((r.features or {}).get(c) or 0.0) for r in pop) or 1.0)
                for c in cols}

        def zvec(feats: dict) -> list[float]:
            return [(float((feats or {}).get(c) or 0.0) - means[c]) / stds[c] for c in cols]

        tz = zvec(target.features)
        dists = [(r.spotify_track_id, math.dist(tz, zvec(r.features)))
                 for r in pop if r.spotify_track_id != track_id]
        dists.sort(key=lambda x: x[1])
        return dists[:k]

    def job_status(self, track_ids: list[str]) -> dict[str, int]:
        """Progress for a visitor's set: total / cached / queued / running / failed."""
        ids = list(dict.fromkeys(track_ids))
        cached = len(self.cached_ids(ids))
        with self._Session() as s:
            statuses = s.execute(
                select(ExtractionJob.status).where(
                    ExtractionJob.spotify_track_id.in_(ids))
            ).scalars().all()
        c = Counter(statuses)
        return {"total": len(ids), "cached": cached,
                "queued": c.get(JOB_QUEUED, 0), "running": c.get(JOB_RUNNING, 0),
                "failed": c.get(JOB_FAILED, 0)}
