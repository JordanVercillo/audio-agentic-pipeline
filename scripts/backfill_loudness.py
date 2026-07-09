"""
backfill_loudness.py — add the within-track loudness curve to already-cached
tracks (F-v2a), from the LOCAL owner MP3s — no re-download.

Audio is transient for the worker (D-15), but the owner corpus MP3s still live
in data/raw_audio/. This reads each one, computes just the loudness curve (RMS
only — cheap), and updates the cache's loudness_curve column via a targeted
write that leaves the seeded feature columns untouched. Idempotent.

    uv run python scripts/backfill_loudness.py            # all cached tracks with a local MP3
    uv run python scripts/backfill_loudness.py --force    # recompute even if a curve exists
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
from src.dsp.feature_extractor import loudness_curve_from_signal  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_RAW_AUDIO = _ROOT / "data" / "raw_audio"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the F-v2 loudness curve from local MP3s.")
    parser.add_argument("--force", action="store_true",
                        help="recompute even for tracks that already have a curve")
    args = parser.parse_args()

    if not _RAW_AUDIO.is_dir():
        print(f"No local audio at {_RAW_AUDIO} — nothing to backfill.")
        return 0

    cache = FeatureCache()
    done = skipped = no_row = failed = 0
    for mp3 in sorted(_RAW_AUDIO.glob("*.mp3")):
        track_id = mp3.stem
        if cache.loudness_curve(track_id) is not None and not args.force:
            skipped += 1
            continue
        try:
            curve = loudness_curve_from_signal(load_audio(mp3))
            if cache.set_loudness_curve(track_id, curve):
                done += 1
            else:
                no_row += 1  # MP3 exists but the track isn't cached — skip quietly
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the backfill
            failed += 1
            print(f"  {track_id}: {exc}")

    print(f"loudness backfill: {done} updated, {skipped} already had one, "
          f"{no_row} not cached, {failed} failed — db: {cache.engine.url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
