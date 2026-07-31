"""
run_extraction_worker.py — drain the feature-cache extraction queue (APP_SPEC Epic A).

    uv run python scripts/run_extraction_worker.py [--max N]      # drain once
    uv run python scripts/run_extraction_worker.py --loop         # self-host mode:
                                                                  # poll forever (D-16)

Reads DATABASE_URL (SQLite+WAL locally — the default; Postgres if configured).
Audio is fetched to a temp dir and deleted after extraction (D-15); spectrograms
land in data/spectrograms/. In the local-first deployment this runs as the
second process alongside the webapp (APP_SPEC §5).
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

# Force UTF-8 stdout — the reused downloader prints emoji status lines that crash
# a Windows cp1252 console (journal: the Windows-stdout gremlin).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.store import clusters as cl  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402
from src.store.extractor import another_worker_alive, drain  # noqa: E402
from src.store.perceptual import PERCEPTUAL_VERSION, rebuild_marts  # noqa: E402
from src.store.semantic import broken_extraction_ids  # noqa: E402
from src.warehouse.from_cache import export_gold  # noqa: E402

_SPECTROGRAM_DIR = _ROOT / "data" / "spectrograms"
_MARTS_DIR = _ROOT / "data" / "marts"
_MODELED_DIR = _ROOT / "data" / "warehouse" / "modeled"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drain the feature-cache extraction queue.")
    parser.add_argument("--max", type=int, default=None,
                        help="max jobs to process per drain (default: the whole queue)")
    parser.add_argument("--loop", action="store_true",
                        help="poll the queue forever (self-host worker mode)")
    parser.add_argument("--interval", type=int, default=30,
                        help="seconds between polls in --loop mode (default 30)")
    parser.add_argument("--takeover", action="store_true",
                        help="start even if another worker's heartbeat looks alive")
    # P4.6.4 debounce. The rebuild ALWAYS runs the moment the queue empties, so
    # these only govern how often it runs DURING a long drain.
    parser.add_argument("--rebuild-after", type=int, default=50,
                        help="rebuild derived planes after N new tracks (default 50)")
    parser.add_argument("--rebuild-every", type=float, default=10.0,
                        help="...or after this many minutes with work pending "
                             "(default 10)")
    args = parser.parse_args()

    cache = FeatureCache()

    # Single-instance lock: two workers double-extract (wasted downloads/DSP)
    # and can double-write the same spectrogram file. A fresh heartbeat from
    # another pid means one is already running.
    hb = cache.heartbeat("extraction-worker")
    if not args.takeover and another_worker_alive(hb, os.getpid()):
        print(f"another extraction worker looks ALIVE (pid {hb['pid']}, last beat "
              f"{hb['beat_at']}) — two workers double-extract. Refusing to start; "
              f"use --takeover if that worker is actually gone.")
        sys.exit(1)

    def beat() -> None:
        cache.beat("extraction-worker", pid=os.getpid(), interval_seconds=args.interval)

    # P4.6.4 — debounce the derived-plane rebuild. The chain (marts + dedup +
    # gold + freshness) is O(corpus): measured 5.31 s over 1,946 tracks
    # = 2.73 ms/track, so it outgrows a 30 s poll at ~11k tracks — INSIDE the
    # playlist-import trajectory, not at some distant scale. Worst case is
    # steady drip-feeding: a full O(N) rebuild for the 2 tracks that finished
    # this poll. Rebuild when enough has accumulated, or enough time has
    # passed, and ALWAYS the moment the queue empties, so a finished import
    # still reaches /explore immediately.
    pending_rebuild = 0
    last_rebuild = 0.0
    with tempfile.TemporaryDirectory(prefix="va_audio_") as audio_dir:
        while True:
            # The whole poll body is guarded: a transient DB error (e.g. a
            # SQLite snapshot-stale write promotion under WAL, which busy_timeout
            # does NOT retry) must cost ONE poll, not kill the only consumer and
            # strand the queue forever. extract_one is already per-track-guarded.
            try:
                # A previous worker may have died mid-job — reclaim its orphans
                # (status 'running' blocks re-enqueue until reset).
                requeued = cache.requeue_stale_running()
                if requeued:
                    print(f"re-queued {len(requeued)} stale running job(s)")
                # A failed-under-cap job was only ever retried by a dashboard
                # visit or a playlist import that happened to include it — so a
                # playlist-imported track's retry never came, and it sat at
                # attempt 1 forever while /library called it "analyzing…".
                # Attempts are preserved, so this converges: success, or
                # dead-lettered into the needs-source queue for a human.
                retryable = cache.requeue_retryable()
                if retryable:
                    print(f"re-queued {len(retryable)} retryable failed job(s)")
                beat()
                result = drain(cache, audio_dir=Path(audio_dir),
                               spectrogram_dir=_SPECTROGRAM_DIR, max_jobs=args.max,
                               on_progress=beat)
                if result["done"] or result["failed"]:
                    print(f"extraction: {result['done']} done, {result['failed']} failed")
                pending_rebuild += int(result["done"])
                try:
                    queue_empty = cache.queue_count() == 0
                except Exception:  # noqa: BLE001 — unknown queue → treat as busy
                    queue_empty = False
                due = pending_rebuild and (
                    queue_empty                                   # drain idle
                    or pending_rebuild >= args.rebuild_after      # enough new work
                    or (time.time() - last_rebuild) >= args.rebuild_every * 60)
                if due:
                    print(f"derived rebuild ({pending_rebuild} new track(s), "
                          f"queue {'empty' if queue_empty else 'busy'})")
                    pending_rebuild = 0
                    last_rebuild = time.time()
                    # New tracks → refresh the derived layer + marts so they reach
                    # /explore immediately (percentiles recalibrate by design).
                    try:
                        marts = rebuild_marts(cache, _MARTS_DIR)
                        print(f"marts refreshed: {marts['n_tracks']} tracks in "
                              f"{PERCEPTUAL_VERSION}")
                    except Exception as exc:  # noqa: BLE001 — derived layer, never fatal
                        print(f"mart refresh failed (next successful drain retries): {exc}")
                    # O1 (D-28) dedup flags are refreshed INSIDE rebuild_marts
                    # (its first act, so every mart sees the current canonical
                    # plane). This used to call refresh_duplicate_flags a second
                    # time right here — pure duplicated work on every drain.
                    try:
                        # D-60: the GOLD catalog plane. Only the serving marts
                        # were refreshed here, so every import left dim_tracks
                        # behind and GOLD_PLANE_STALE came back on its own —
                        # 983 tracks adrift after one week of imports. The
                        # exporter is deterministic and idempotent (a rerun is
                        # byte-identical), so there is no reason it should have
                        # needed a human. The drift PLANE is deliberately
                        # untouched: its per-user grain can't be honestly
                        # reproduced for the user-agnostic corpus.
                        gold = export_gold(cache, _MODELED_DIR)
                        print(f"gold catalog refreshed: {gold['dim_tracks']} tracks")
                    except Exception as exc:  # noqa: BLE001 — derived, never fatal
                        print(f"gold export failed (next drain retries): {exc}")
                    try:
                        # Surface data-quality problems the moment they enter the
                        # corpus instead of waiting for someone to run the audit.
                        # REPORT ONLY — a quarantine deletes analysis, and that
                        # stays the owner's call (the Q3/D-52 doctrine); the
                        # named script does it with a dry run and a backup.
                        broken = broken_extraction_ids(cache)
                        if broken:
                            print(f"⚠ {len(broken)} broken extraction(s) "
                                  f"(tempo 0 / silent): {', '.join(sorted(broken)[:5])}"
                                  f"{' …' if len(broken) > 5 else ''} — review with "
                                  f"scripts/quarantine_broken_extractions.py")
                    except Exception as exc:  # noqa: BLE001 — a report, never fatal
                        print(f"broken-extraction check failed: {exc}")
                    try:
                        # D-62: the model plane closes itself too. Session 50
                        # hand-fixed cluster coverage 39%->99.7% and it was back
                        # to 36.7% seven days later, because the fix was a
                        # command rather than a trigger. Training is cheap and
                        # additive, so it happens here automatically; PROMOTION
                        # is the identity event and stays deliberate — an
                        # identity-stable retrain (same k, matched centroids,
                        # unchanged words) self-promotes, anything else prints
                        # the diff and waits for a human.
                        f = cl.freshness(cache, "song")
                        # A non-identity-stable retrain is NOT promoted, so the
                        # SERVED model stays stale, so freshness stays true —
                        # and the worker would retrain every single poll
                        # forever, writing ~1 model + ~N cluster rows each time
                        # (~3 min of CPU at the current corpus). If a candidate
                        # already exists for essentially this corpus, waiting
                        # for the human is the whole point.
                        _cand = cl.newest_model(cache, "song")
                        _pending = (_cand is not None and _cand.promoted_at is None
                                    and (_cand.n_trained or 0) >= 0.95 * f["n_population"])
                        if _pending:
                            print(f"cluster model {_cand.id} is trained and awaiting "
                                  f"review — not retraining (uv run python "
                                  f"scripts/promote_cluster_model.py --model {_cand.id})")
                        if f["stale"] and not _pending:
                            print(f"cluster model stale ({'; '.join(f['reasons'])}) "
                                  f"— retraining")
                            res = cl.train_song_clusters(cache)
                            if res and not res.get("promoted"):
                                served = cl.latest_model(cache, "song")
                                with cache._Session() as _s:
                                    from src.store.models import ClusterModel
                                    cand = _s.get(ClusterModel, res["model_id"])
                                    imap = (cl.match_identity(served, cand)
                                            if served is not None else None)
                                if imap:
                                    cl.promote_model(cache, res["model_id"],
                                                     identity_map=imap)
                                    print(f"  model {res['model_id']} promoted "
                                          f"(identity-stable, remapped)")
                                else:
                                    print(f"  ⚠ model {res['model_id']} is trained but "
                                          f"NOT identity-stable — it changes what "
                                          f"visitors see. Review:\n"
                                          f"    uv run python scripts/"
                                          f"promote_cluster_model.py --model "
                                          f"{res['model_id']}")
                    except Exception as exc:  # noqa: BLE001 — derived, never fatal
                        print(f"cluster freshness check failed: {exc}")
            except Exception as exc:  # noqa: BLE001 — one bad poll must not kill the worker
                print(f"worker poll error (continuing next interval): {exc}")
            if not args.loop:
                break
            time.sleep(args.interval)
