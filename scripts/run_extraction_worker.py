"""
run_extraction_worker.py — drain the feature-cache extraction queue (APP_SPEC Epic A).

    uv run python scripts/run_extraction_worker.py [--max N]

Reads DATABASE_URL (Postgres in prod, SQLite locally). Audio is fetched to a
temp dir and deleted after extraction (D-15); spectrograms land in
data/spectrograms/ (GCS in prod). Run as a Cloud Run Job / background worker.
"""

import argparse
import sys
import tempfile
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
from src.store.extractor import drain  # noqa: E402

_SPECTROGRAM_DIR = _ROOT / "data" / "spectrograms"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drain the feature-cache extraction queue.")
    parser.add_argument("--max", type=int, default=None,
                        help="max jobs to process (default: drain the whole queue)")
    args = parser.parse_args()

    cache = FeatureCache()
    with tempfile.TemporaryDirectory(prefix="va_audio_") as audio_dir:
        result = drain(cache, audio_dir=Path(audio_dir),
                       spectrogram_dir=_SPECTROGRAM_DIR, max_jobs=args.max)
    print(f"extraction: {result['done']} done, {result['failed']} failed")
