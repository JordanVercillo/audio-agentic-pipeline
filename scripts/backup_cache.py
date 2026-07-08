"""
backup_cache.py — back up / verify / restore the feature cache (Epic E, D-17).

    uv run python scripts/backup_cache.py                      # create a backup
    uv run python scripts/backup_cache.py --keep 14            # prune to newest 14
    uv run python scripts/backup_cache.py --verify <zip>       # what's inside?
    uv run python scripts/backup_cache.py --restore <zip>      # restore (drill!)

Schedule the bare command nightly (Task Scheduler) — see docs/SELF_HOSTING.md.
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

from src.store.backup import backup, restore, verify  # noqa: E402

_DB = _ROOT / "data" / "feature_cache.db"
_SPECTROGRAMS = _ROOT / "data" / "spectrograms"
_BACKUPS = _ROOT / "backups"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature-cache backup tooling (D-17).")
    parser.add_argument("--keep", type=int, default=10, help="backups to retain (default 10)")
    parser.add_argument("--verify", metavar="ZIP", help="report a backup's contents and exit")
    parser.add_argument("--restore", metavar="ZIP", help="restore a backup over data/")
    args = parser.parse_args()

    if args.verify:
        rep = verify(Path(args.verify))
        print(f"{args.verify}: {rep['tracks']} tracks, {rep['spectrograms']} spectrograms")
    elif args.restore:
        rep = restore(Path(args.restore), _DB, _SPECTROGRAMS)
        print(f"restored {rep['tracks']} tracks + {rep['spectrograms']} spectrograms "
              f"(previous db kept as {_DB.name}.pre-restore)")
    else:
        zip_path = backup(_DB, _SPECTROGRAMS, _BACKUPS, keep=args.keep)
        rep = verify(zip_path)
        print(f"backup: {zip_path} — {rep['tracks']} tracks, "
              f"{rep['spectrograms']} spectrograms (keeping {args.keep})")
