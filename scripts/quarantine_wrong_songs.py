"""
quarantine_wrong_songs.py — remove low-confidence acquisitions from the corpus
(DQ, 2026-07-23). The D-52 run's PRE-affinity-gate swaps (rounds 1-2) locked in
some wrong-song audio via the resume marker; this finds them and quarantines
their wrong analysis so the owner can repair them by hand (D-56).

"Not confident" = exactly what the affinity gate would REJECT today: the
re_extract.title_affinity check (a meaningful title token overlaps the video
title/channel, or squashed-title containment). Reusing the gate's own function
means we only quarantine what the current pipeline would never have accepted —
principled, not ad-hoc. Legit low-MATCH-CONFIDENCE remixes (the S2 electronic
band) are NOT touched: they have real title affinity, only a low heuristic
score.

    uv run python scripts/quarantine_wrong_songs.py            # DRY RUN (default)
    uv run python scripts/quarantine_wrong_songs.py --execute  # back up + quarantine

Execute: backs up the cache, deletes each track's wrong features/perceptual/
provenance/cluster + spectrogram, dead-letters its job (worker won't re-grab),
and files it in the needs-source ledger. Then rebuild marts + retrain.
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
from src.store.re_extract import title_affinity  # noqa: E402

_DATA = _ROOT / "data"
_SPECTROGRAMS = _DATA / "spectrograms"
_LEDGER = _DATA / "re_extract_ledger.json"


def find_not_confident(cache: FeatureCache) -> list[dict]:
    """Current-per-key provenance rows whose video does NOT look like the track
    (the affinity gate would reject). Analyzed tracks only."""
    analyzed = set(cache.all_features())
    seen: set[str] = set()
    out: list[dict] = []
    for r in cache.all_provenance():                 # newest-first
        tid = r["spotify_track_id"]
        if tid in seen:
            continue
        seen.add(tid)
        if tid not in analyzed:
            continue
        m = cache.get_meta(tid) or {}
        if not title_affinity(m.get("track_name"), m.get("artist_names"),
                              r.get("youtube_title"), r.get("channel")):
            out.append({"id": tid, "track": m.get("track_name"),
                        "artist": m.get("artist_names"),
                        "youtube_title": r.get("youtube_title"),
                        "url": r.get("youtube_url")})
    return out


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
            "error": f"quarantined wrong-song swap — needs a manual source "
                     f"(was: {(r['youtube_title'] or '')[:80]!r})",
            "at": None, "attempts": 1}
    tmp = _LEDGER.with_suffix(".curate.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_LEDGER)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quarantine low-confidence (wrong-song) acquisitions.")
    parser.add_argument("--execute", action="store_true",
                        help="actually quarantine (default is a dry run)")
    args = parser.parse_args()

    cache = FeatureCache()
    rows = find_not_confident(cache)
    print(f"{len(rows)} not-confident acquisition(s) "
          f"(the affinity gate would reject these):\n")
    for r in rows:
        print(f"  {r['track']!r} — {r['artist']!r}")
        print(f"      got: {r['youtube_title']!r}")

    if not rows:
        print("\nnothing to quarantine — the corpus is clean.")
        return 0
    if not args.execute:
        print(f"\nDRY RUN — nothing changed. Re-run with --execute to quarantine "
              f"these {len(rows)} tracks (a backup is taken first).")
        return 0

    from src.store.backup import backup
    dest = backup(_DATA / "feature_cache.db", _SPECTROGRAMS, _ROOT / "backups")
    print(f"\nbacked up: {dest}")

    reasons = {r["id"]: f"quarantined wrong-song swap (was {(r['youtube_title'] or '')[:60]!r})"
               for r in rows}
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
    print("NEXT: rebuild marts + retrain (the finish checklist), then the owner "
          "repairs them via /library?filter=needs-source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
