"""
describe_clusters.py — generate grounded descriptions for the latest song
clusters (K3, additive-only D-5).

Offline batch by design: a description is a pure function of the trained
model's (label, dims) — frozen until the next retrain — so we pay the LLM
once here, never per-request and never inside the mart-rebuild hook. Each
description is grounded in the K3a label_dims (the exact evidence that named
the bucket); a model reply that drops a dim word degrades to the
deterministic template. Idempotent: a model that already has descriptions
under the current prompt contract is skipped unless --force.

    uv run python scripts/describe_clusters.py            # fill if missing/stale
    uv run python scripts/describe_clusters.py --force    # regenerate all
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

from src.store.cache import FeatureCache  # noqa: E402
from src.store.clusters import (  # noqa: E402
    cluster_description_inputs,
    latest_model,
    save_descriptions,
)
from src.webapp.prompt_contract import CLUSTER_PROMPT_VERSION  # noqa: E402
from src.webapp.rag import TasteRAG  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate grounded cluster descriptions (K3, offline batch).")
    parser.add_argument("--force", action="store_true",
                        help="regenerate even when current-contract descriptions exist")
    args = parser.parse_args()

    cache = FeatureCache()
    model = latest_model(cache, "song")
    if model is None:
        print("no trained song model — nothing to describe (train clusters first).")
        return 0

    existing = getattr(model, "descriptions", None) or {}
    current = {cid for cid, d in existing.items()
               if (d or {}).get("prompt_version") == CLUSTER_PROMPT_VERSION}
    inputs = cluster_description_inputs(cache, model)
    if not args.force and current >= {c["cluster_id"] for c in inputs}:
        print(f"model #{model.id}: all {len(inputs)} clusters already described "
              f"under {CLUSTER_PROMPT_VERSION} — nothing to do (use --force).")
        return 0

    rag = TasteRAG()
    print(f"model #{model.id} (k={model.k}): describing {len(inputs)} clusters "
          f"via {rag.model if rag._wants_llm() else 'the deterministic template'}…")
    descriptions: dict[str, dict] = {}
    for c in inputs:
        r = rag.describe_cluster(c)
        descriptions[c["cluster_id"]] = {
            "text": r["description"], "source": r["source"],
            "prompt_version": r["prompt_version"]}
        print(f"  [{c['cluster_id']}] {c['label']!r} ({r['source']}): {r['description']}")
    if not save_descriptions(cache, model.id, descriptions):
        print("model row vanished mid-run — nothing written.")
        return 1
    n_llm = sum(1 for d in descriptions.values() if d["source"] == "llm")
    print(f"saved {len(descriptions)} descriptions ({n_llm} llm, "
          f"{len(descriptions) - n_llm} template) to model #{model.id}. "
          "Rebuild marts (or wait for the next drain) to project them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
