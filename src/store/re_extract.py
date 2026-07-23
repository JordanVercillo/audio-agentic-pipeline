"""
re_extract.py — the D-52 full-corpus re-extraction program (Q3, Epic Q).

Uniformly re-acquires + re-extracts already-analyzed tracks through the Q1
provenance-carrying matcher, so every track gets (a) audio matched by the
duration-aware heuristic and (b) a verifiable `track_provenance` row (∅→✓).

The batch-plan invariants (Fable-signed session 54; red-team hardened —
data-platform review, findings F1-F3 + corrections all folded in):
    - ATOMIC SWAP ON SUCCESS ONLY, and a TRUE swap: `cache.upsert(...,
      replace_display=True)` fires only after a full acquire→DSP pass and
      takes the new audio's values verbatim (F2: preserve-on-None would mix
      an old source's curve/meter with new features). ANY failure leaves the
      old row byte-identical.
    - Failures go to a RUNNER LEDGER (gitignored, temp+replace durable JSON),
      never to provenance — a failed re-acquisition teaches nothing about
      where the CURRENT audio came from, so /song's ∅ stays honest.
    - Queue discipline: the runner never CREATES or FAILS a job. (Honesty per
      red-team #4: upsert's mark-done is an idempotent no-op on the ~689
      already-'done' rows — accepted, not hidden.)
    - RESUMABLE: success marker = a track_provenance row exists, and the
      runner VERIFIES the row landed (a swap whose provenance write failed is
      ledgered for retry — the rare double-extract is accepted, red-team #5).
      Provenance ALWAYS wins over a stale ledger entry.
    - SCOPE: analyzed canonicals only (796 live = 807 − 11 twins — the honest
      100%; twins ride their canonical, metadata-only rows are queue territory).
    - ORDER (value-first, deterministic tiers): ① broken (tempo≤1) ② non-null
      stored match_confidence ascending ③ NULL-confidence (unmeasured pre-O2,
      unrankable — not necessarily good) by id.
    - AUDIO SCRATCH DIR: the caller passes a dedicated scratch dir, NEVER
      data/raw_audio (F3: the download would overwrite a pre-existing
      {id}.mp3 and the transient-delete would then destroy it).
    - A re-extract that SUCCEEDS but still measures broken features (tempo≤1)
      is swapped honestly (it is the real measurement), stays feature_valid-
      gated, and is FLAGGED in the ledger for Q4 — never auto-dead-lettered
      (a deletion is the owner's call; red-team #8: Q&A's conf-1.0 breakage
      is a DSP/silence issue that will likely reproduce).

The frozen 77-dim contract is untouched — same extract_features, same
DSP_VERSION; what changes is the AUDIO the features are measured from.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .cache import FeatureCache
from .extractor import DSP_VERSION, AcquireFn, _record_provenance, default_acquire

logger = logging.getLogger(__name__)

_BROKEN_TEMPO = 1.0  # mirrors clusters._MIN_VALID_TEMPO_BPM / the mart gate


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── the ledger (failures + run history; successes live in track_provenance) ──
class Ledger:
    """Gitignored JSON sidecar: {failed: {id: {error, at, attempts}}, runs: [...]}.
    Data is rebuildable (ground rule 7) — losing the ledger only means failed
    ids get retried, never that work is redone (provenance is the success marker)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {"failed": {}, "runs": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("ledger unreadable at %s — starting fresh", self.path)

    def failed_ids(self) -> set[str]:
        return set(self.data.get("failed", {}))

    def record_failure(self, track_id: str, error: str) -> None:
        f = self.data.setdefault("failed", {})
        prev = f.get(track_id) or {}
        f[track_id] = {"error": error[:300], "at": _utc(),
                       "attempts": int(prev.get("attempts", 0)) + 1}
        self._save()

    def clear_failure(self, track_id: str) -> None:
        if track_id in self.data.get("failed", {}):
            del self.data["failed"][track_id]
            self._save()

    def flag(self, track_id: str, note: str) -> None:
        """A non-failure observation for Q4's QA reader (e.g. swapped but the
        new measurement is STILL broken — real, gated, needs human eyes)."""
        self.data.setdefault("flags", {})[track_id] = {"note": note[:300], "at": _utc()}
        self._save()

    def record_run(self, summary: dict) -> None:
        self.data.setdefault("runs", []).append({"at": _utc(), **summary})
        self._save()

    def _save(self) -> None:
        """Temp+replace — an 11h run dying mid-write must not corrupt its own
        resume file (red-team #7b)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


# ── target selection (scope + order) ─────────────────────────────────────────
def select_targets(cache: FeatureCache) -> list[str]:
    """Analyzed canonicals in value-first order: broken → ascending stored
    match_confidence (NULLs after) → id. Deterministic."""
    feats = cache.all_features()
    metas = {r["id"]: r for r in cache.library_rows()}
    conf = cache.all_match_confidence()

    def is_twin(tid: str) -> bool:
        return bool((metas.get(tid) or {}).get("duplicate_of"))

    def is_broken(f: dict) -> bool:
        t = f.get("tempo_bpm")
        return isinstance(t, (int, float)) and t <= _BROKEN_TEMPO

    ids = [t for t in feats if not is_twin(t)]

    def key(tid: str):
        broken = 0 if is_broken(feats[tid]) else 1
        c = conf.get(tid)
        return (broken, 0 if c is not None else 1, c if c is not None else 0.0, tid)

    return sorted(ids, key=key)


# ── the per-track swap ────────────────────────────────────────────────────────
def re_extract_one(cache: FeatureCache, track_id: str, *, audio_dir: Path,
                   spectrogram_dir: Path, acquire: AcquireFn = default_acquire,
                   ) -> tuple[bool, str]:
    """Re-acquire + re-extract ONE analyzed track. Returns (ok, note).

    Success → upsert with replace_display=True (a TRUE swap — the new audio's
    artifacts verbatim, F2) + a VERIFIED provenance row. Failure → nothing is
    written; the caller ledgers it. Never raises; never creates or fails a job.
    `audio_dir` MUST be a scratch dir, never data/raw_audio (F3)."""
    from ..dsp.audio_loader import load_audio
    from ..dsp.feature_extractor import extract_features
    from .extractor import make_mel_spectrogram

    meta = cache.get_meta(track_id)
    if not meta or not meta.get("track_name"):
        return False, "no metadata for the audio search"

    audio_path: Optional[Path] = None
    try:
        dur_ms = meta.get("duration_ms")
        audio_path, match = acquire(track_id, meta["track_name"],
                                    meta.get("artist_names") or "", Path(audio_dir),
                                    (dur_ms / 1000.0) if dur_ms else None)
        if audio_path is None or not Path(audio_path).exists():
            return False, "audio acquisition failed"
        signal = load_audio(audio_path)
        tf = extract_features(signal)
        features = tf.to_summary_dict()
        spec_uri = make_mel_spectrogram(signal,
                                        Path(spectrogram_dir) / f"{track_id}.png")
        cache.upsert(track_id, features, spectrogram_uri=str(spec_uri),
                     source="youtube", dsp_version=DSP_VERSION,
                     loudness_curve=tf.loudness_curve_points(),
                     time_signature=tf.time_signature,
                     beat_times=tf.beat_times_list(),
                     sections=tf.sections_list(),
                     match_confidence=(match or {}).get("confidence"),
                     replace_display=True)
        # the provenance row is the RESUME MARKER — a swallowed write must
        # surface as a per-track failure (retried; rare double-extract accepted)
        if _record_provenance(cache, track_id, match) <= 0:
            return False, "provenance write failed (features already swapped)"
        t = features.get("tempo_bpm")
        if isinstance(t, (int, float)) and t <= _BROKEN_TEMPO:
            return True, "swapped — STILL BROKEN (tempo≤1), feature_valid-gated, Q4 review"
        return True, "swapped"
    except Exception as exc:  # noqa: BLE001 — one bad track must never stop the run
        return False, str(exc)
    finally:
        if audio_path is not None:  # D-15: only the file WE downloaded is transient
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass


# ── the program loop ──────────────────────────────────────────────────────────
def run(cache: FeatureCache, *, audio_dir: Path, spectrogram_dir: Path,
        ledger: Ledger, limit: Optional[int] = 25, retry_failed: bool = False,
        acquire: AcquireFn = default_acquire, marts_dir: Optional[Path] = None,
        ) -> dict[str, Any]:
    """One resumable invocation: pick up to `limit` un-done targets, swap them,
    ledger the failures, rebuild marts once at the end if anything changed."""
    done_ids = {r["spotify_track_id"] for r in cache.all_provenance()}
    # reconciliation (red-team #7a): provenance ALWAYS wins — a track that has
    # since succeeded (any path) sheds its stale ledger entry.
    for tid in ledger.failed_ids() & done_ids:
        ledger.clear_failure(tid)
    skip_failed = set() if retry_failed else ledger.failed_ids()
    targets = [t for t in select_targets(cache)
               if t not in done_ids and t not in skip_failed]
    remaining_before = len(targets)
    if limit is not None:
        targets = targets[:limit]

    t0 = time.monotonic()
    ok = failed = 0
    for i, tid in enumerate(targets, 1):
        meta = cache.get_meta(tid) or {}
        success, note = re_extract_one(cache, tid, audio_dir=audio_dir,
                                       spectrogram_dir=spectrogram_dir,
                                       acquire=acquire)
        if success:
            ok += 1
            ledger.clear_failure(tid)
            if "STILL BROKEN" in note:
                ledger.flag(tid, note)  # honest swap, dead measurement → Q4 eyes
        else:
            failed += 1
            ledger.record_failure(tid, note)
        logger.info("[%d/%d] %s %r — %s", i, len(targets),
                    "OK " if success else "FAIL", meta.get("track_name") or tid, note)

    if ok and marts_dir is not None:
        from .perceptual import rebuild_marts
        rebuild_marts(cache, marts_dir)  # the established post-drain hook

    summary = {"attempted": len(targets), "ok": ok, "failed": failed,
               "remaining": remaining_before - len(targets),
               "elapsed_s": round(time.monotonic() - t0, 1)}
    ledger.record_run(summary)
    return summary
