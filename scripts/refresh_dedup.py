"""refresh_dedup.py — recompute the near-duplicate display flags (Epic O / D-28).

Recomputes TrackMeta.duplicate_of over the whole cache (the cosine tiebreak
refines pairs where both are analyzed). Annotation-ONLY — never touches features,
jobs, or the bridge key. Run on demand; the extraction worker also refreshes this
after each drain.

    uv run python scripts/refresh_dedup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.store.cache import FeatureCache  # noqa: E402


def main() -> int:
    r = FeatureCache().refresh_duplicate_flags()
    print(f"dedup refresh: {r['n_duplicates']} duplicate flag(s) across "
          f"{r['n_clusters']} cluster(s) over {r['n_metas']} metas "
          f"({r['n_updated']} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
