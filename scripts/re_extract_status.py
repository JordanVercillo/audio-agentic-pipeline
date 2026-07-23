"""re_extract_status.py — a read-only progress view of the D-52 full run (Q3).

    uv run python scripts/re_extract_status.py

Reads the provenance table (the resume marker = ground truth), the runner
ledger, and the log tail — safe to run any time, including mid-run.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.store.cache import FeatureCache  # noqa: E402
from src.store.re_extract import select_targets  # noqa: E402

_LOG = _ROOT / "logs" / "re_extract.err.log"
_LEDGER = _ROOT / "data" / "re_extract_ledger.json"
_LINE = re.compile(r"^\[(\d+)/(\d+)\] (OK|FAIL)\s+(.*)$")


def main() -> int:
    cache = FeatureCache()
    done = {r["spotify_track_id"] for r in cache.all_provenance()}
    scope = select_targets(cache)
    remaining = [t for t in scope if t not in done]
    pct = 100.0 * (len(scope) - len(remaining)) / len(scope) if scope else 0.0

    print(f"D-52 re-extraction — {len(scope) - len(remaining)}/{len(scope)} "
          f"({pct:.1f}%) · {len(remaining)} remaining")

    ledger = {}
    if _LEDGER.exists():
        try:
            ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))
        except ValueError:
            pass
    failed, flagged = ledger.get("failed", {}), ledger.get("flags", {})
    print(f"ledger: {len(failed)} failed · {len(flagged)} flagged still-broken")
    for tid, info in list(failed.items())[:5]:
        print(f"   FAIL {tid}: {info.get('error', '')[:70]}")

    if _LOG.exists():
        lines = [ln for ln in _LOG.read_text(encoding="utf-8", errors="replace"
                                             ).splitlines() if _LINE.match(ln)]
        if lines:
            print(f"last: {lines[-1]}")
            mtime = datetime.fromtimestamp(_LOG.stat().st_mtime, tz=timezone.utc)
            age = (datetime.now(timezone.utc) - mtime).total_seconds()
            print(f"log last written {age:.0f}s ago"
                  + ("  ⚠ STALLED?" if age > 600 else ""))
    if remaining:
        eta_h = len(remaining) * 55 / 3600.0   # ~55 s/track observed
        print(f"ETA ≈ {eta_h:.1f} h at ~55 s/track")
    else:
        print("COVERAGE COMPLETE — run the post-run checklist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
