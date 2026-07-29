"""
quarantine_broken_extractions.py — remove DSP output that is the broken/silent
signature (tempo 0, ≈ −180 dBFS). The fourth sibling of
`quarantine_wrong_songs.py` (wrong SONG), `quarantine_bad_durations.py` (wrong
LENGTH) and `quarantine_wrong_versions.py` (wrong TAKE); this one is wrong
DECODE — the audio arrived but librosa got nothing usable out of it.

WHY THIS IS NOT AUTOMATIC. The worker reports these the moment they appear
(post-drain), but stops there: quarantining DELETES a track's analysis, and
deletion is the owner's call (the Q3/D-52 doctrine, restated at every quarantine
script). Reporting is cheap and safe; acting is neither.

Detection reuses `semantic.broken_extraction_ids` — the SAME function the mart's
feature_valid gate and the worker's report use — so "broken" cannot come to mean
three different things. It is also why this is honest rather than a way to make
FEATURE_DISTRIBUTION go green: the audit flags these because the DATA is wrong,
and the fix is to remove the bad row, never to loosen the check (journal #53).

    uv run python scripts/quarantine_broken_extractions.py            # DRY RUN
    uv run python scripts/quarantine_broken_extractions.py --execute  # back up + remove

Execute: backs up the cache, deletes each track's features/perceptual/
provenance/cluster + spectrogram, DEAD-LETTERS its job (so the worker cannot
silently re-acquire the same unusable audio) and files it in the needs-source
queue for a D-56 manual repair. Bridge key untouched; reversible by supplying a
correct source.
"""

import argparse
import json
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
from src.store.semantic import broken_extraction_ids  # noqa: E402

_DATA = _ROOT / "data"
_SPECTROGRAMS = _DATA / "spectrograms"
_LEDGER = _DATA / "re_extract_ledger.json"


def _write_ledger(ids: list[str]) -> None:
    data = {"failed": {}, "runs": [], "flags": {}}
    if _LEDGER.exists():
        try:
            data = json.loads(_LEDGER.read_text(encoding="utf-8"))
        except ValueError:
            pass
    failed = data.setdefault("failed", {})
    for t in ids:
        failed[t] = {"error": "quarantined broken extraction — the audio decoded "
                              "to silence (tempo 0); needs a manual source",
                     "at": None, "attempts": 1}
    tmp = _LEDGER.with_suffix(".curate.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_LEDGER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="actually quarantine (default is a dry run)")
    args = parser.parse_args()

    cache = FeatureCache()
    ids = sorted(broken_extraction_ids(cache))
    metas = cache.all_meta()
    print(f"{len(ids)} broken extraction(s) — tempo 0 / silent decode:\n")
    for t in ids:
        m = metas.get(t, {})
        print(f"  {str(m.get('track_name'))[:44]:44s} | {str(m.get('artist_names'))[:26]}")

    if not ids:
        print("\nnothing to quarantine.")
        return 0
    if not args.execute:
        print(f"\nDRY RUN — nothing changed. Re-run with --execute to remove these "
              f"{len(ids)} analyses (a backup is taken first).")
        return 0

    from src.store.backup import backup
    dest = backup(_DATA / "feature_cache.db", _SPECTROGRAMS, _ROOT / "backups")
    print(f"\nbacked up: {dest}")

    n = cache.quarantine_tracks(
        {t: "quarantined broken extraction (tempo 0 / silent decode)" for t in ids})
    removed = 0
    for t in ids:
        p = _SPECTROGRAMS / f"{t}.png"
        if p.exists():
            p.unlink()
            removed += 1
    _write_ledger(ids)
    print(f"quarantined {n} track(s); removed {removed} spectrogram(s); "
          f"filed in the needs-source queue.")
    print("NEXT: the worker rebuilds the marts + gold plane on its next drain; "
          "repair them via /library?filter=needs-source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
