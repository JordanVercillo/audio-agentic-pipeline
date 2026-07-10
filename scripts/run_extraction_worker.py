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

from src.store.cache import FeatureCache  # noqa: E402
from src.store.extractor import another_worker_alive, drain  # noqa: E402
from src.store.perceptual import PERCEPTUAL_VERSION, rebuild_marts  # noqa: E402

_SPECTROGRAM_DIR = _ROOT / "data" / "spectrograms"
_MARTS_DIR = _ROOT / "data" / "marts"

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
                beat()
                result = drain(cache, audio_dir=Path(audio_dir),
                               spectrogram_dir=_SPECTROGRAM_DIR, max_jobs=args.max,
                               on_progress=beat)
                if result["done"] or result["failed"]:
                    print(f"extraction: {result['done']} done, {result['failed']} failed")
                if result["done"]:
                    # New tracks → refresh the derived layer + marts so they reach
                    # /explore immediately (percentiles recalibrate by design).
                    try:
                        marts = rebuild_marts(cache, _MARTS_DIR)
                        print(f"marts refreshed: {marts['n_tracks']} tracks in "
                              f"{PERCEPTUAL_VERSION}")
                    except Exception as exc:  # noqa: BLE001 — derived layer, never fatal
                        print(f"mart refresh failed (next successful drain retries): {exc}")
            except Exception as exc:  # noqa: BLE001 — one bad poll must not kill the worker
                print(f"worker poll error (continuing next interval): {exc}")
            if not args.loop:
                break
            time.sleep(args.interval)
