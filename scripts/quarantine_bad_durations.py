"""
quarantine_bad_durations.py — remove duration-implausible acquisitions (DQ,
D-59, 2026-07-24). The sibling of `quarantine_wrong_songs.py`: that one reuses
`title_affinity` to catch WRONG-SONG audio; this one reuses `implausible_duration`
to catch WRONG-LENGTH audio — a full album / DJ set / 2-hour source stored as a
single track.

The live finding: Taylor Swift's "The Tortured Poets Department" was analyzed at
7300 s (2 h) because Spotify's `duration_ms` was 0/missing, so the ratio guard
couldn't fire and the old worker admitted it. It sits in the aggregate corpus
(it's source-validated) and trips FEATURE_DISTRIBUTION. Loosening the audit to
accept it would gate-mask bad data (D-55 criterion ④ forbids exactly that), so
we remove the row instead — and the hardened guard now rejects the class at
ingestion.

"Bad length" = exactly what `implausible_duration` rejects today (now including
the missing-Spotify-length absolute cap). Reusing the gate's own function means
we only quarantine what the current pipeline would never accept — principled,
not ad-hoc. A legitimately-longer remix judged against its own Spotify length is
NOT touched.

    uv run python scripts/quarantine_bad_durations.py            # DRY RUN (default)
    uv run python scripts/quarantine_bad_durations.py --execute  # back up + quarantine

Execute: backs up the cache, deletes each track's wrong features/perceptual/
provenance/cluster + spectrogram, dead-letters its job, files it in the
needs-source ledger. Then rebuild marts (the finish checklist).
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

from src.ingestion.match_gate import implausible_duration  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_DATA = _ROOT / "data"
_SPECTROGRAMS = _DATA / "spectrograms"
_LEDGER = _DATA / "re_extract_ledger.json"


def find_bad_durations(cache: FeatureCache,
                       include_withheld: bool = False) -> list[dict]:
    """Analyzed tracks whose STORED audio length is implausible for the track —
    the hardened `implausible_duration` over (measured duration_sec, Spotify
    duration_s). Includes the missing-Spotify-length case (measured > 30 min).

    By default only tracks that ACTUALLY shape an aggregate are returned
    (source-validated, non-twin) — those are the ones that trip the audit and
    the only ones removing changes any number. The rest are already withheld
    (B2/D-57) and excluded everywhere; `include_withheld=True` returns them too
    for a fuller cleanup, but they don't affect the audit."""
    feats = cache.all_features()
    durs = cache.all_durations_ms()
    metas = cache.all_meta()
    validated, twins = cache.source_validated_ids(), cache.twin_ids()
    out: list[dict] = []
    for tid, f in feats.items():
        measured = f.get("duration_sec")
        if not isinstance(measured, (int, float)):
            continue
        expected_s = (durs.get(tid) or 0) / 1000.0
        if not implausible_duration(measured, expected_s):
            continue
        in_aggregate = tid in validated and tid not in twins
        if not include_withheld and not in_aggregate:
            continue
        m = metas.get(tid, {})
        out.append({"id": tid, "track": m.get("track_name"),
                    "artist": m.get("artist_names"),
                    "measured_s": round(float(measured)),
                    "spotify_s": round(expected_s),
                    "in_aggregate": in_aggregate})
    return sorted(out, key=lambda r: -r["measured_s"])


def _write_ledger(rows: list[dict]) -> None:
    data = {"failed": {}, "runs": [], "flags": {}}
    if _LEDGER.exists():
        try:
            data = json.loads(_LEDGER.read_text(encoding="utf-8"))
        except ValueError:
            pass
    failed = data.setdefault("failed", {})
    for r in rows:
        failed[r["id"]] = {
            "error": f"quarantined bad-duration acquisition — {r['measured_s']}s "
                     f"stored for a {r['spotify_s']}s track; needs a manual source",
            "at": None, "attempts": 1}
    tmp = _LEDGER.with_suffix(".curate.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_LEDGER)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quarantine duration-implausible (wrong-length) acquisitions.")
    parser.add_argument("--execute", action="store_true",
                        help="actually quarantine (default is a dry run)")
    parser.add_argument("--include-withheld", action="store_true",
                        help="also quarantine already-withheld bad-duration tracks "
                             "(fuller cleanup; does not affect the audit)")
    args = parser.parse_args()

    cache = FeatureCache()
    rows = find_bad_durations(cache, include_withheld=args.include_withheld)
    scope = "all" if args.include_withheld else "aggregate-affecting"
    print(f"{len(rows)} duration-implausible acquisition(s) [{scope}] "
          f"(the guard would reject these):\n")
    for r in rows:
        print(f"  {r['track']!r} — {r['artist']!r}")
        print(f"      stored {r['measured_s']}s for a {r['spotify_s']}s track")

    if not rows:
        print("\nnothing to quarantine — no implausible durations.")
        return 0
    if not args.execute:
        print(f"\nDRY RUN — nothing changed. Re-run with --execute to quarantine "
              f"these {len(rows)} tracks (a backup is taken first).")
        return 0

    from src.store.backup import backup
    dest = backup(_DATA / "feature_cache.db", _SPECTROGRAMS, _ROOT / "backups")
    print(f"\nbacked up: {dest}")

    reasons = {r["id"]: f"quarantined bad-duration ({r['measured_s']}s for "
                        f"{r['spotify_s']}s)" for r in rows}
    n = cache.quarantine_tracks(reasons)
    removed_png = 0
    for r in rows:
        p = _SPECTROGRAMS / f"{r['id']}.png"
        if p.exists():
            p.unlink()
            removed_png += 1
    _write_ledger(rows)
    print(f"quarantined {n} track(s); removed {removed_png} spectrogram(s); "
          f"filed in the needs-source queue.")
    print("NEXT: rebuild marts (build_feature_marts). The owner repairs them "
          "via /library?filter=needs-source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
