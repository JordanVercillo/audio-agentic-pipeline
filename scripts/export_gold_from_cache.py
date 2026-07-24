"""
export_gold_from_cache.py — refresh the batch gold catalog from the live cache (D-60).

Unifies the two data planes' CATALOG: writes a current, canonical `dim_tracks`
+ track-grain `fact_track_features` (+ refreshed `dim_artists`) into
`data/warehouse/modeled/`, so the MCP server reads the same deduped corpus the
app serves. Leaves the `fact_listening_features` drift plane intact (its
per-user time_range grain can't be honestly reproduced for the grown corpus).

    uv run python scripts/export_gold_from_cache.py

Deterministic + idempotent: reruns are byte-identical. Read-only on the cache
(never touches the bridge key or the frozen 77-dim vector). After it runs,
re-run the warehouse audit — DUPLICATE_TRACKS clears and the plane-agreement
check passes.
"""

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

from src.store.cache import FeatureCache  # noqa: E402
from src.warehouse.from_cache import export_gold  # noqa: E402

_MODELED = _ROOT / "data" / "warehouse" / "modeled"


def main() -> int:
    cache = FeatureCache()
    counts = export_gold(cache, _MODELED)
    print(f"gold catalog refreshed from the cache -> {_MODELED}")
    for name, n in counts.items():
        print(f"  {name:22s} {n}")
    print("\nfact_listening_features (the drift plane) left untouched.")
    print("NEXT: uv run .claude/skills/warehouse-audit/audit_warehouse.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
