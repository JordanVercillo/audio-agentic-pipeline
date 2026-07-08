# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Knowledge-base sync + validation (see kb/KB_SPEC.md).

Usage (from the language-models repo root):
    uv run kb/_tools/sync_kb.py --check                 # validate cards + index
    uv run kb/_tools/sync_kb.py --to <consumer-repo>    # validate, then copy kb/ -> <repo>/notes/kb/
    uv run kb/_tools/sync_kb.py --to <repo> --dest docs/kb   # custom destination subpath

Sync is one-way: canonical -> consumer. The copy gets KB_PROVENANCE.md
(source commit, version, date). Consumer copies are never hand-edited.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

KB = Path(__file__).resolve().parents[1]          # .../language-models/kb
REPO = KB.parent
REQUIRED = ("id", "title", "type", "origin", "tags", "use_when", "maturity", "version_added")
TYPES = {"technique", "concept", "lesson", "pattern"}
MATURITY = {"proven", "promising", "caution"}


def frontmatter(path: Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, "no frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "unterminated frontmatter"
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError as e:
        return None, f"YAML error: {e}"
    return (data, None) if isinstance(data, dict) else (None, "frontmatter not a mapping")


def check() -> list[str]:
    errors: list[str] = []
    index_text = (KB / "KB_INDEX.md").read_text(encoding="utf-8")
    if not re.search(r"\*\*Version:\*\*\s*\d{4}\.\d{2}\.\d{2}", index_text):
        errors.append("KB_INDEX.md: missing/malformed **Version:** YYYY.MM.DD")

    ids: set[str] = set()
    for card in sorted((KB / "techniques").glob("*.md")):
        data, err = frontmatter(card)
        if err:
            errors.append(f"{card.name}: {err}")
            continue
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            errors.append(f"{card.name}: missing fields {missing}")
        cid = str(data.get("id", ""))
        if cid != card.stem:
            errors.append(f"{card.name}: id '{cid}' != filename stem")
        if cid in ids:
            errors.append(f"{card.name}: duplicate id '{cid}'")
        ids.add(cid)
        if data.get("type") not in TYPES:
            errors.append(f"{card.name}: type '{data.get('type')}' not in {sorted(TYPES)}")
        if data.get("maturity") not in MATURITY:
            errors.append(f"{card.name}: maturity '{data.get('maturity')}' not in {sorted(MATURITY)}")
        if cid and cid not in index_text:
            errors.append(f"{card.name}: id not listed in KB_INDEX.md")

    for required_file in ("KB_SPEC.md", "weeks/COURSE_SUMMARY.md",
                          "skills/SKILL_PATTERNS.md", "tools/TOOLING.md"):
        if not (KB / required_file).exists():
            errors.append(f"missing required file: kb/{required_file}")
    return errors


def source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def kb_version() -> str:
    m = re.search(r"\*\*Version:\*\*\s*(\d{4}\.\d{2}\.\d{2})",
                  (KB / "KB_INDEX.md").read_text(encoding="utf-8"))
    return m.group(1) if m else "unknown"


def sync(target_repo: Path, dest_sub: str) -> Path:
    dest = target_repo / dest_sub
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(KB, dest, ignore=shutil.ignore_patterns("__pycache__"))
    n_files = sum(1 for p in dest.rglob("*") if p.is_file())
    (dest / "KB_PROVENANCE.md").write_text(
        f"# KB Provenance — READ-ONLY COPY\n\n"
        f"| | |\n|---|---|\n"
        f"| Source | `{REPO}` (github JordanVercillo/language-models, `kb/`) |\n"
        f"| Source commit | `{source_commit()}` |\n"
        f"| KB version | {kb_version()} |\n"
        f"| Synced | {date.today().isoformat()} |\n"
        f"| Files | {n_files} |\n\n"
        f"Do NOT edit this folder — changes belong upstream (see KB_SPEC.md §1).\n"
        f"Refresh: run `uv run kb/_tools/sync_kb.py --to {target_repo}` from the source repo.\n",
        encoding="utf-8",
    )
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--to", type=Path, help="consumer repo root to sync into")
    ap.add_argument("--dest", default="notes/kb", help="destination subpath (default notes/kb)")
    args = ap.parse_args()

    errors = check()
    for e in errors:
        print(f"CHECK FAIL: {e}")
    if not errors:
        print(f"CHECK OK: kb v{kb_version()} — cards + index valid")
    if args.check or not args.to:
        return 1 if errors else 0

    if errors:
        print("refusing to sync with validation errors")
        return 1
    if not args.to.is_dir():
        print(f"target repo not found: {args.to}")
        return 1
    dest = sync(args.to.resolve(), args.dest)
    print(f"SYNCED: kb v{kb_version()} -> {dest}")
    print("Remember to commit in the consumer repo ('KB sync <version>').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
