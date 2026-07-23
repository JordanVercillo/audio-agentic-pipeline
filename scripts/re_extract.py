"""
re_extract.py — run the D-52 full-corpus re-extraction program (Q3, Epic Q).

Resumable, value-first (broken → lowest match-confidence → rest), atomic
swap on success only; failures ride a gitignored ledger, never provenance.
The full corpus is ~807 tracks at ~50-90 s each (~12-16 h) — run it in
owner-scheduled --limit batches; every invocation is safe to interrupt.

    uv run python scripts/re_extract.py                 # one batch (default 25)
    uv run python scripts/re_extract.py --limit 3       # the dry-run slice
    uv run python scripts/re_extract.py --all           # the full owner-scheduled run
    uv run python scripts/re_extract.py --retry-failed  # reattempt ledgered failures

BEFORE the full run: uv run python scripts/backup_cache.py
AFTER full coverage:  train_clusters → describe_clusters --force → build marts
                      → warehouse-audit + app-verify (the runner prints this
                      checklist when nothing remains).
"""

import argparse
import logging
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
from src.store.re_extract import Ledger, run  # noqa: E402

_DATA = _ROOT / "data"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="D-52 re-extraction: uniform re-acquire + re-extract with provenance.")
    parser.add_argument("--limit", type=int, default=25,
                        help="tracks this invocation (default 25)")
    parser.add_argument("--all", action="store_true",
                        help="no cap — the owner-scheduled full run")
    parser.add_argument("--retry-failed", action="store_true",
                        help="reattempt ids the ledger marked failed")
    args = parser.parse_args()

    cache = FeatureCache()
    ledger = Ledger(_DATA / "re_extract_ledger.json")
    # F3 (red-team): a dedicated scratch dir — NEVER data/raw_audio, where the
    # download would overwrite a pre-existing {id}.mp3 and the transient-delete
    # would then destroy a file this run didn't create.
    scratch = _DATA / "tmp_reextract"
    scratch.mkdir(parents=True, exist_ok=True)
    summary = run(cache,
                  audio_dir=scratch,
                  spectrogram_dir=_DATA / "spectrograms",
                  ledger=ledger,
                  limit=None if args.all else args.limit,
                  retry_failed=args.retry_failed,
                  marts_dir=_DATA / "marts")
    print(f"\nbatch: {summary['ok']} swapped · {summary['failed']} failed "
          f"(ledgered) · {summary['remaining']} still to go "
          f"· {summary['elapsed_s']}s")
    if summary["remaining"] == 0 and summary["failed"] == 0:
        print("COVERAGE COMPLETE — the post-run checklist:\n"
              "  1. uv run python scripts/train_clusters.py\n"
              "  2. uv run python scripts/describe_clusters.py --force\n"
              "  3. uv run python scripts/build_feature_marts.py\n"
              "  4. uv run .claude/skills/warehouse-audit/audit_warehouse.py\n"
              "  5. uv run .claude/skills/app-verify/verify_app.py\n"
              "  6. app_control restart + a live browser check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
