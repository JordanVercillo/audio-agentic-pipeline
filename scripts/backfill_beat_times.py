"""
backfill_beat_times.py — populate the beat grid for already-cached tracks
(F-v2c), from the LOCAL owner MP3s — no re-download.

Same pattern as backfill_loudness.py / backfill_time_signature.py: the corpus
MP3s in data/raw_audio/ survive even though the worker deletes its audio (D-15).
This reads each one, detects beat times (onset + beat tracking only), and writes
them to the cache's beat_times column via a targeted update. Idempotent.

    uv run python scripts/backfill_beat_times.py            # cached tracks with a local MP3
    uv run python scripts/backfill_beat_times.py --force    # recompute even if set
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
from src.dsp.feature_extractor import beat_grid_from_signal  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_RAW_AUDIO = _ROOT / "data" / "raw_audio"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the F-v2c beat grid from local MP3s.")
    parser.add_argument("--force", action="store_true",
                        help="recompute even for tracks that already have a beat grid")
    args = parser.parse_args()

    if not _RAW_AUDIO.is_dir():
        print(f"No local audio at {_RAW_AUDIO} — nothing to backfill.")
        return 0

    cache = FeatureCache()
    done = skipped = no_row = failed = total_beats = 0
    for mp3 in sorted(_RAW_AUDIO.glob("*.mp3")):
        track_id = mp3.stem
        if cache.beat_times(track_id) is not None and not args.force:
            skipped += 1
            continue
        try:
            beats = beat_grid_from_signal(load_audio(mp3))
            if cache.set_beat_times(track_id, beats):
                done += 1
                total_beats += len(beats)
            else:
                no_row += 1  # MP3 present but track not cached — skip quietly
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the backfill
            failed += 1
            print(f"  {track_id}: {exc}")

    avg = (total_beats / done) if done else 0
    print(f"beat-grid backfill: {done} updated ({avg:.0f} beats/track avg), "
          f"{skipped} already set, {no_row} not cached, {failed} failed — db: {cache.engine.url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
