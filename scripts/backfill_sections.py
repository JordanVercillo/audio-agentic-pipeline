"""
backfill_sections.py — detect structural sections for already-cached tracks
(F-v3), from the LOCAL owner MP3s — no re-download.

Same pattern as the other F-v2/F-v3 backfills: data/raw_audio/ survives even
though the worker's audio is transient (D-15). Reads each MP3, runs the
Laplacian section detector (chroma + MFCC + beats + RMS; no HPSS), and writes
the sections via a targeted update that leaves everything else untouched.
Idempotent.

    uv run python scripts/backfill_sections.py            # cached tracks with a local MP3
    uv run python scripts/backfill_sections.py --force    # recompute even if set
"""

import argparse
import sys
from collections import Counter
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
from src.dsp.feature_extractor import sections_from_signal  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_RAW_AUDIO = _ROOT / "data" / "raw_audio"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill F-v3 sections from local MP3s.")
    parser.add_argument("--force", action="store_true",
                        help="recompute even for tracks that already have sections")
    args = parser.parse_args()

    if not _RAW_AUDIO.is_dir():
        print(f"No local audio at {_RAW_AUDIO} — nothing to backfill.")
        return 0

    cache = FeatureCache()
    done = skipped = no_row = failed = 0
    n_sections = Counter()   # sections-per-track distribution (journal #21 habit)
    n_types = Counter()      # distinct section types per track
    for mp3 in sorted(_RAW_AUDIO.glob("*.mp3")):
        track_id = mp3.stem
        if cache.sections(track_id) is not None and not args.force:
            skipped += 1
            continue
        try:
            secs = sections_from_signal(load_audio(mp3))
            if cache.set_sections(track_id, secs):
                done += 1
                n_sections[len(secs)] += 1
                n_types[len({s["label"] for s in secs})] += 1
            else:
                no_row += 1  # MP3 present but track not cached — skip quietly
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the backfill
            failed += 1
            print(f"  {track_id}: {exc}")

    def _hist(c: Counter) -> str:
        return ", ".join(f"{k}×{v}" for k, v in sorted(c.items()))

    print(f"sections backfill: {done} updated, {skipped} already set, "
          f"{no_row} not cached, {failed} failed — db: {cache.engine.url}.")
    if done:
        print(f"  sections/track: {{{_hist(n_sections)}}}")
        print(f"  section types/track: {{{_hist(n_types)}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
