"""
run_pipeline.py — One-Command Pipeline Runner
================================================
Clears the warehouse, runs the temporal analysis notebook end-to-end,
and prints a summary of everything that was built.

Usage:
    python scripts/run_pipeline.py           # full run
    python scripts/run_pipeline.py --clean   # clear warehouse only
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
STAGING_DIR = WAREHOUSE_DIR / "staging"
CLEANSED_DIR = WAREHOUSE_DIR / "cleansed"
MODELED_DIR = WAREHOUSE_DIR / "modeled"
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "temporal_analysis.ipynb"


def clean_warehouse():
    """Remove all Parquet files from warehouse layers."""
    print("\n🧹 Cleaning warehouse...")
    total = 0
    for layer_dir in [STAGING_DIR, CLEANSED_DIR, MODELED_DIR]:
        if layer_dir.exists():
            files = list(layer_dir.glob("*.parquet"))
            for f in files:
                f.unlink()
                total += 1
            print(f"   {layer_dir.name:10s} → removed {len(files)} file(s)")
        else:
            layer_dir.mkdir(parents=True, exist_ok=True)
            print(f"   {layer_dir.name:10s} → created (empty)")
    print(f"   Total: {total} file(s) removed")


def run_notebook():
    """Execute the temporal analysis notebook via nbconvert."""
    try:
        import nbformat
        from nbconvert.preprocessors import ExecutePreprocessor
    except ImportError:
        print("❌ Missing dependency: pip install nbconvert")
        sys.exit(1)

    print(f"\n🚀 Executing {NOTEBOOK_PATH.name}...")
    start = time.time()

    nb = nbformat.read(str(NOTEBOOK_PATH), as_version=4)
    ep = ExecutePreprocessor(timeout=180, kernel_name="python3")

    try:
        ep.preprocess(nb, {"metadata": {"path": str(NOTEBOOK_PATH.parent)}})
    except Exception as e:
        print(f"\n❌ Notebook execution failed at cell:")
        print(f"   {e}")
        sys.exit(1)

    elapsed = time.time() - start
    code_cells = sum(1 for c in nb.cells if c.cell_type == "code")
    print(f"   ✅ {code_cells} code cells executed in {elapsed:.1f}s")

    return nb


def print_summary():
    """Print a summary of what's in the warehouse after execution."""
    print("\n📊 Warehouse Summary:")
    print("   " + "─" * 45)

    for layer_dir in [STAGING_DIR, CLEANSED_DIR, MODELED_DIR]:
        files = sorted(layer_dir.glob("*.parquet")) if layer_dir.exists() else []
        total_kb = sum(f.stat().st_size for f in files) / 1024
        print(f"\n   {layer_dir.name.upper()} ({len(files)} files, {total_kb:.1f} KB)")
        for f in files:
            size = f.stat().st_size / 1024
            print(f"      {f.name:45s} {size:6.1f} KB")

    print("\n   " + "─" * 45)
    print("   ✅ Pipeline complete\n")


def main():
    # Ensure emoji/unicode output works on Windows
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Temporal Audio Pipeline Runner")
    parser.add_argument("--clean", action="store_true", help="Clear warehouse only (no execution)")
    args = parser.parse_args()

    print("=" * 50)
    print("  🎧 Temporal Audio Pipeline")
    print("=" * 50)

    clean_warehouse()

    if args.clean:
        print("\n   Done (clean only).")
        return

    run_notebook()
    print_summary()


if __name__ == "__main__":
    main()
