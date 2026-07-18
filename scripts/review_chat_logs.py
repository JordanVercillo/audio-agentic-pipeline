"""
review_chat_logs.py — run a D-47 chat review session.

The flywheel: sample ungraded chat turns -> a human grades them -> the grades
(ChatLabel) become new golden cases + the K5 adapter dataset, and the report is
the chat's running pipeline-health metric.

    uv run python scripts/review_chat_logs.py --sample 20   # -> a grading worksheet
    #   ... open the worksheet, fill accuracy/usefulness/verdict on each card ...
    uv run python scripts/review_chat_logs.py --commit data/chat_review/<file>.jsonl
    uv run python scripts/review_chat_logs.py --report     # aggregates -> evals/runs/

Worksheets live under data/chat_review/ (gitignored — raw user text NEVER
reaches the public repo, rule 7). Only the aggregates-only report is committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.store.cache import FeatureCache  # noqa: E402
from src.webapp import chat_review  # noqa: E402
from src.webapp.prompt_contract import PROMPT_VERSION  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_WORKSHEETS = _ROOT / "data" / "chat_review"
_RUNS = _ROOT / "evals" / "runs"

# the human fills these on each worksheet card (the machine-checkable ones are
# pre-suggested); rubric-v1 anchors are in the ChatLabel model.
_HUMAN_FIELDS = {"accuracy": None, "usefulness": None, "verdict": None,
                 "missing_fact": None, "notes": None}


def cmd_sample(cache: FeatureCache, size: int) -> int:
    pool = cache.ungraded_chat_turns()
    cards = chat_review.render_worksheet(chat_review.stratified_sample(pool, size))
    if not cards:
        print("no ungraded chat turns to review.")
        return 0
    _WORKSHEETS.mkdir(parents=True, exist_ok=True)
    out = _WORKSHEETS / f"{date.today().isoformat()}_worksheet.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for c in cards:
            c.update({k: v for k, v in _HUMAN_FIELDS.items()})  # blanks for the human
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {len(cards)} cards -> {out}")
    print("fill accuracy(0-2)/usefulness(0-2)/verdict on each, then --commit it.")
    print("pre-graded (citation_fidelity + invention) suggestions are in each card.")
    return 0


def cmd_commit(cache: FeatureCache, path: str) -> int:
    n = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        card = json.loads(line)
        if card.get("accuracy") is None and card.get("verdict") is None:
            continue  # ungraded card — skip
        sug = card.get("suggested") or {}
        cache.write_chat_label(
            log_id=card["log_id"], rubric_version="rubric-v1",
            accuracy=card.get("accuracy"), usefulness=card.get("usefulness"),
            citation_fidelity=card.get("citation_fidelity", sug.get("citation_fidelity")),
            invention=card.get("invention", sug.get("invention")),
            verdict=card.get("verdict"), missing_fact=card.get("missing_fact"),
            golden_proposal=card.get("golden_proposal"), grader=card.get("grader") or "jordan",
            notes=card.get("notes"))
        n += 1
    print(f"committed {n} graded labels.")
    return 0


def cmd_report(cache: FeatureCache) -> int:
    labels = cache.all_chat_labels()
    logs = {r["id"]: r for r in cache.recent_chat_turns(10000)}
    enriched = [{**lb, "mode": logs.get(lb["log_id"], {}).get("mode"),
                 "source": logs.get(lb["log_id"], {}).get("source")} for lb in labels]
    report = chat_review.aggregate(enriched)
    text = chat_review.format_report(report, prompt_version=PROMPT_VERSION)
    print(text)
    _RUNS.mkdir(parents=True, exist_ok=True)
    out = _RUNS / f"{date.today().isoformat()}_chatlog_review.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nwrote aggregates-only report -> {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="D-47 chat review session.")
    p.add_argument("--sample", type=int, metavar="N", help="write a grading worksheet of N cards")
    p.add_argument("--commit", metavar="FILE", help="ingest a filled worksheet -> ChatLabel rows")
    p.add_argument("--report", action="store_true", help="aggregates-only report -> evals/runs/")
    args = p.parse_args()
    cache = FeatureCache()
    if args.sample:
        return cmd_sample(cache, args.sample)
    if args.commit:
        return cmd_commit(cache, args.commit)
    if args.report:
        return cmd_report(cache)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
