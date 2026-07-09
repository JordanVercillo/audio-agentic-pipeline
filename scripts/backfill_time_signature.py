"""
backfill_time_signature.py — estimate the meter for already-cached tracks
(F-v2b), from the LOCAL owner MP3s — no re-download.

Same pattern as backfill_loudness.py: the owner corpus MP3s in data/raw_audio/
survive even though the worker deletes its audio (D-15). This reads each one,
estimates the time signature (onset + beat tracking only), and writes it to the
cache's time_signature column via a targeted update. Idempotent.

    uv run python scripts/backfill_time_signature.py            # cached tracks with a local MP3
    uv run python scripts/backfill_time_signature.py --force    # recompute even if set
"""

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.dsp.audio_loader import load_audio  # noqa: E402
from src.dsp.feature_extractor import time_signature_from_signal  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_RAW_AUDIO = _ROOT / "data" / "raw_audio"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the F-v2 meter estimate from local MP3s.")
    parser.add_argument("--force", action="store_true",
                        help="recompute even for tracks that already have a meter")
    args = parser.parse_args()

    if not _RAW_AUDIO.is_dir():
        print(f"No local audio at {_RAW_AUDIO} — nothing to backfill.")
        return 0

    cache = FeatureCache()
    have = cache.all_time_signatures()
    done = skipped = no_row = failed = 0
    hist: dict[int, int] = {}
    for mp3 in sorted(_RAW_AUDIO.glob("*.mp3")):
        track_id = mp3.stem
        if track_id in have and not args.force:
            skipped += 1
            continue
        try:
            ts = time_signature_from_signal(load_audio(mp3))
            if cache.set_time_signature(track_id, ts):
                done += 1
                hist[ts] = hist.get(ts, 0) + 1
            else:
                no_row += 1  # MP3 present but track not cached — skip quietly
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the backfill
            failed += 1
            print(f"  {track_id}: {exc}")

    dist = ", ".join(f"{k}/4×{v}" for k, v in sorted(hist.items()))
    print(f"time-signature backfill: {done} updated, {skipped} already set, "
          f"{no_row} not cached, {failed} failed — meters: {{{dist}}} — db: {cache.engine.url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
