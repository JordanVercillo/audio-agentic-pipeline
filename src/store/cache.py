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
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, event, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from .models import (
    Base,
    ExtractionJob,
    TrackFeatures,
    TrackMeta,
    TrackPerceptual,
    WorkerHeartbeat,
    utcnow,
)

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
# A track that fails this many times is dead-lettered — a permanently-unfetchable
# track (deleted/region-locked YouTube video, always-erroring DSP) must NOT
# hot-loop re-download+re-DSP on every dashboard visit. attempts is preserved
# across retries (never reset) so the cap actually bites.
MAX_ATTEMPTS = 3


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
        self._migrate_added_columns()
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    # Forward-only column adds (create_all never ALTERs an existing table).
    # A DB created before a column was introduced gets it here, idempotently —
    # existing rows read NULL. Both SQLite and Postgres take ADD COLUMN online.
    _ADDED_COLUMNS = {"track_features": {"loudness_curve": "JSON",
                                         "time_signature": "INTEGER",
                                         "beat_times": "JSON",
                                         "sections": "JSON"},
                      "track_meta": {"popularity": "INTEGER"}}

    def _migrate_added_columns(self) -> None:
        inspector = sa_inspect(self.engine)
        for table, columns in self._ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            missing = {name: typ for name, typ in columns.items() if name not in present}
            for name, typ in missing.items():
                try:  # each ALTER its own txn: a first-boot race where the other
                    with self.engine.begin() as conn:  # process added it first is fine
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
                except OperationalError:
                    pass  # duplicate column (added concurrently) — self-heals

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
               source: str = "youtube", dsp_version: Optional[str] = None,
               loudness_curve: Optional[list] = None,
               time_signature: Optional[int] = None,
               beat_times: Optional[list] = None,
               sections: Optional[list] = None) -> None:
        """Store a song's features (idempotent) and mark any pending job done.

        Display artifacts (spectrogram_uri, loudness_curve, time_signature,
        beat_times, sections) are PRESERVED when a caller doesn't supply them —
        merge would otherwise NULL them. This makes a features-only re-write
        (e.g. re-running seed_cache after the F-v2/F-v3 backfills) truly
        idempotent instead of wiping every backfilled artifact.
        """
        with self._Session() as s:
            existing = s.get(TrackFeatures, track_id)
            if existing is not None:
                if spectrogram_uri is None:
                    spectrogram_uri = existing.spectrogram_uri
                if loudness_curve is None:
                    loudness_curve = existing.loudness_curve
                if not time_signature:
                    time_signature = existing.time_signature
                if beat_times is None:
                    beat_times = existing.beat_times
                if sections is None:
                    sections = existing.sections
            s.merge(TrackFeatures(
                spotify_track_id=track_id, features=features,
                tempo_bpm=_f(features.get("tempo_bpm")),
                rms_mean=_f(features.get("rms_mean")),
                spectral_centroid_mean=_f(features.get("spectral_centroid_mean")),
                spectrogram_uri=spectrogram_uri, extraction_source=source,
                dsp_version=dsp_version, loudness_curve=loudness_curve,
                time_signature=(int(time_signature) if time_signature else None),
                beat_times=beat_times, sections=sections, extracted_at=utcnow()))
            job = s.get(ExtractionJob, track_id)
            if job is not None:
                job.status = JOB_DONE
                job.last_error = None
            s.commit()

    def set_time_signature(self, track_id: str, time_signature: int) -> bool:
        """Update ONLY a cached track's estimated meter (F-v2 backfill). No-op if absent."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            if row is None:
                return False
            row.time_signature = int(time_signature) if time_signature else None
            s.commit()
            return True

    def all_time_signatures(self) -> dict[str, int]:
        """Every cached track's estimated meter (only rows that have one)."""
        with self._Session() as s:
            rows = s.execute(
                select(TrackFeatures.spotify_track_id, TrackFeatures.time_signature)
                .where(TrackFeatures.time_signature.isnot(None))).all()
        return {tid: int(ts) for tid, ts in rows}

    def time_signature(self, track_id: str) -> Optional[int]:
        """A single track's estimated meter, or None."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            return int(row.time_signature) if row and row.time_signature else None

    def set_loudness_curve(self, track_id: str, curve: list) -> bool:
        """Update ONLY a cached track's loudness curve (F-v2 backfill).

        A targeted column update — unlike upsert it won't disturb the row's
        features/provenance, so backfilling the curve from a local MP3 can't
        clobber the warehouse-seeded feature columns. No-op if the row is absent.
        """
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            if row is None:
                return False
            row.loudness_curve = curve
            s.commit()
            return True

    def loudness_curve(self, track_id: str) -> Optional[list]:
        """The stored within-track loudness curve (dBFS points), or None."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            return row.loudness_curve if row is not None else None

    def loudness_curves(self, track_ids: list[str]) -> dict[str, list]:
        """Stored loudness curves for the given ids (only rows that have one) —
        the corpus-roll-up input for the /analytics average loudness arc."""
        if not track_ids:
            return {}
        with self._Session() as s:
            rows = s.execute(
                select(TrackFeatures.spotify_track_id, TrackFeatures.loudness_curve)
                .where(TrackFeatures.spotify_track_id.in_(track_ids))
                .where(TrackFeatures.loudness_curve.isnot(None))).all()
        return {tid: curve for tid, curve in rows if curve}

    def set_beat_times(self, track_id: str, beat_times: list) -> bool:
        """Update ONLY a cached track's beat grid (F-v2c backfill). No-op if absent."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            if row is None:
                return False
            row.beat_times = beat_times
            s.commit()
            return True

    def beat_times(self, track_id: str) -> Optional[list]:
        """The stored detected beat times (seconds), or None."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            return row.beat_times if row is not None else None

    def set_sections(self, track_id: str, sections: list) -> bool:
        """Update ONLY a cached track's detected sections (F-v3 backfill)."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            if row is None:
                return False
            row.sections = sections
            s.commit()
            return True

    def sections(self, track_id: str) -> Optional[list]:
        """The stored detected sections, or None (analyzed pre-F-v3)."""
        with self._Session() as s:
            row = s.get(TrackFeatures, track_id)
            return row.sections if row is not None else None

    # ── perceptual-v1 layer (VISION_SPECS F1) ────────────────────────────────
    def upsert_perceptual(self, track_id: str, features: dict, *,
                          version: str, computed_at=None) -> None:
        with self._Session() as s:
            s.merge(TrackPerceptual(spotify_track_id=track_id, features=features,
                                    version=version,
                                    computed_at=computed_at or utcnow()))
            s.commit()

    def get_perceptual(self, track_ids: list[str]) -> dict[str, dict]:
        if not track_ids:
            return {}
        with self._Session() as s:
            rows = s.execute(
                select(TrackPerceptual).where(
                    TrackPerceptual.spotify_track_id.in_(track_ids))
            ).scalars().all()
        return {r.spotify_track_id: r.features for r in rows}

    def all_perceptual(self) -> dict[str, dict]:
        with self._Session() as s:
            rows = s.execute(select(TrackPerceptual)).scalars().all()
        return {r.spotify_track_id: r.features for r in rows}

    # ── track metadata (for the worker's YouTube query) ─────────────────────
    def remember_meta(self, items: list[dict]) -> None:
        """Upsert minimal metadata (name/artist) so the worker can search for the
        audio, plus last-seen popularity (fetched context). Preserve-if-absent:
        an item that omits a field never NULLs what an earlier fetch stored."""
        if not items:
            return
        with self._Session() as s:
            for it in items:
                tid = it.get("spotify_track_id") or it.get("id")
                if not tid:
                    continue
                pop = it.get("popularity")
                pop = int(pop) if pop is not None else None
                row = s.get(TrackMeta, tid)
                if row is None:
                    s.add(TrackMeta(
                        spotify_track_id=tid,
                        track_name=it.get("track_name") or it.get("name"),
                        artist_names=it.get("artist_names") or it.get("artist"),
                        album_name=it.get("album_name"), popularity=pop))
                    continue
                row.track_name = it.get("track_name") or it.get("name") or row.track_name
                row.artist_names = (it.get("artist_names") or it.get("artist")
                                    or row.artist_names)
                row.album_name = it.get("album_name") or row.album_name
                if pop is not None:
                    row.popularity = pop  # last sight wins; absent keeps the old value
            s.commit()

    def all_popularity(self) -> dict[str, int]:
        """Every track's last-seen Spotify popularity (only rows that have one) —
        the corpus baseline for the taste-vs-popularity context line."""
        with self._Session() as s:
            rows = s.execute(
                select(TrackMeta.spotify_track_id, TrackMeta.popularity)
                .where(TrackMeta.popularity.isnot(None))).all()
        return {tid: int(p) for tid, p in rows}

    def get_meta(self, track_id: str) -> Optional[dict]:
        with self._Session() as s:
            m = s.get(TrackMeta, track_id)
            if m is None:
                return None
            return {"spotify_track_id": m.spotify_track_id, "track_name": m.track_name,
                    "artist_names": m.artist_names, "album_name": m.album_name,
                    "popularity": m.popularity}

    # ── queue ──────────────────────────────────────────────────────────────
    def enqueue(self, track_ids: list[str]) -> list[str]:
        """Queue extraction for uncached ids. Returns the newly-queued ids.

        A brand-new id is queued at attempts=0. A previously-failed id is retried
        (status→queued) ONLY if it's under MAX_ATTEMPTS, and its attempt count is
        preserved so the cap bites; at/over the cap it is dead-lettered (left
        failed, never re-queued). Live (queued/running) jobs are left alone.
        """
        ids = self.missing(track_ids)
        if not ids:
            return []
        with self._Session() as s:
            existing = {j.spotify_track_id: j for j in s.execute(
                select(ExtractionJob).where(ExtractionJob.spotify_track_id.in_(ids))
            ).scalars().all()}
            new: list[str] = []
            for t in ids:
                job = existing.get(t)
                if job is None:
                    s.add(ExtractionJob(spotify_track_id=t, status=JOB_QUEUED, attempts=0))
                    new.append(t)
                elif job.status in (JOB_QUEUED, JOB_RUNNING):
                    continue  # live — don't disturb it
                elif job.status == JOB_FAILED and job.attempts < MAX_ATTEMPTS:
                    job.status = JOB_QUEUED  # retry, PRESERVING attempts (no reset)
                    new.append(t)
                # else: failed & exhausted (dead-letter) → skip, never re-queue
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

    def requeue_stale_running(self, older_than_seconds: int = 900) -> list[str]:
        """Re-queue jobs stuck 'running' past the cutoff — a crashed worker's
        orphans. claim_next marks running and only a live worker ever resolves
        it, so without this a mid-job crash strands the track forever
        (enqueue skips live jobs). Returns the re-queued ids."""
        cutoff = utcnow() - timedelta(seconds=older_than_seconds)
        with self._Session() as s:
            jobs = s.execute(
                select(ExtractionJob).where(
                    ExtractionJob.status == JOB_RUNNING,
                    ExtractionJob.updated_at < cutoff)
            ).scalars().all()
            for job in jobs:
                job.status = JOB_QUEUED
            s.commit()
            return [j.spotify_track_id for j in jobs]

    def beat(self, worker_name: str = "extraction-worker", *,
             pid: Optional[int] = None, interval_seconds: Optional[int] = None) -> None:
        """Record worker liveness (upsert; called once per poll loop)."""
        with self._Session() as s:
            s.merge(WorkerHeartbeat(worker_name=worker_name, pid=pid,
                                    interval_seconds=interval_seconds, beat_at=utcnow()))
            s.commit()

    def heartbeat(self, worker_name: str = "extraction-worker") -> Optional[dict]:
        """The worker's last beat, or None if it has never run."""
        with self._Session() as s:
            hb = s.get(WorkerHeartbeat, worker_name)
            if hb is None:
                return None
            return {"worker_name": hb.worker_name, "pid": hb.pid,
                    "interval_seconds": hb.interval_seconds, "beat_at": hb.beat_at}

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

    def running_ids(self, track_ids: list[str]) -> list[str]:
        """Which of these tracks are being extracted right now (status running) —
        powers the live-progress "analyzing <song>" line without a Spotify call."""
        ids = list(dict.fromkeys(track_ids))
        if not ids:
            return []
        with self._Session() as s:
            rows = s.execute(
                select(ExtractionJob.spotify_track_id).where(
                    ExtractionJob.spotify_track_id.in_(ids),
                    ExtractionJob.status == JOB_RUNNING)
            ).scalars().all()
        return list(rows)
