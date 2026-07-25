"""
quarantine_wrong_versions.py — remove acquisitions of the WRONG TAKE (DQ,
owner call 2026-07-24). The third sibling of `quarantine_wrong_songs.py`
(wrong song, via `title_affinity`) and `quarantine_bad_durations.py` (wrong
length, via `implausible_duration`). This one catches the wrong RECORDING of
the right song, via `match_gate.version_mismatch` over O4's `parse_title`.

THE LIVE FINDING that motivated it: 34 source-validated tracks are showing
features extracted from a different take, and every existing check passes them.

    "on & on - Sammy Virji Remix"   ← "piri & tommy - on & on"   confidence 0.80
    "Low Again - Niall T Remix"     ← "Low Again"                confidence 0.85
    "Goodums - Sammy Virji Remix"   ← "Sammy Virji - If U Need It" (another song)
    "All Night, Pt. 1 - Mixed"      ← "All Night, Pt . 2"

`match_confidence` misses them because it scores the song and the artist, both
of which are right. `title_recall` misses them by design — it measures the CORE
title, so a remix sourced from its original scores 1.0. Only the version tag
sees it, and that only existed as of O4.

Owner decision (2026-07-24): no unverified data on the app. Scope = wrong-take
PLUS the QA3 `review` tier (the song's title is not recognisable in the source).
Mechanism = DELETE the derived data, not withhold it.

    uv run python scripts/quarantine_wrong_versions.py            # DRY RUN (default)
    uv run python scripts/quarantine_wrong_versions.py --execute  # back up + quarantine

Execute: backs up the cache, then for each track deletes features/perceptual/
provenance/cluster + the spectrogram, DEAD-LETTERS the extraction job (so the
worker cannot silently re-grab the same wrong audio — the whole point of
`quarantine_tracks`), and files it in the needs-source ledger for a D-56 manual
repair. The bridge key is untouched: the track still exists, now unanalyzed.
Reversible by supplying a correct source. Then rebuild marts + retrain.
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

from src.ingestion.match_gate import title_recall, version_mismatch  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_DATA = _ROOT / "data"
_SPECTROGRAMS = _DATA / "spectrograms"
_LEDGER = _DATA / "re_extract_ledger.json"

# QA3's own boundary between "probably the right recording, failing the strict
# gate on a technicality" and "the song is not recognisable in this audio".
_TITLE_PRESENT_MIN = 0.5


def _is_manual(prov: dict) -> bool:
    """Owner-supplied audio carries a constant display title, so the matcher
    checks must never judge it (the bug qa_audit found in itself on first run)."""
    return (str(prov.get("matcher_version") or "").startswith("manual")
            or (prov.get("youtube_title") or "") == "Owner-supplied audio file")


def find_wrong_versions(cache: FeatureCache) -> list[dict]:
    """Current provenance rows whose audio is the wrong TAKE, or whose source
    doesn't recognisably contain the song at all.

    Twins are skipped (they hold their own stored analysis but shape no
    aggregate), and so are owner-supplied uploads."""
    metas = cache.all_meta()
    twins = cache.twin_ids()
    feats = set(cache.all_features())
    out: list[dict] = []
    for prov in cache.all_provenance():
        tid = prov.get("spotify_track_id")
        if tid in twins or tid not in feats or _is_manual(prov):
            continue
        m = metas.get(tid) or {}
        name, yt = m.get("track_name"), prov.get("youtube_title")
        if not name or not yt:
            continue
        reason = version_mismatch(name, yt)
        kind = "wrong-take"
        if reason is None:
            if title_recall(name, yt) >= _TITLE_PRESENT_MIN:
                continue
            reason, kind = "the song's title is not recognisable in the source", "unrecognisable"
        out.append({"id": tid, "track": name, "artist": m.get("artist_names"),
                    "source": yt, "reason": reason, "kind": kind,
                    "confidence": prov.get("match_confidence")})
    return sorted(out, key=lambda r: (r["kind"], -(r["confidence"] or 0)))


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
            "error": f"quarantined {r['kind']} acquisition — {r['reason']}; "
                     "needs a manual source",
            "at": None, "attempts": 1}
    tmp = _LEDGER.with_suffix(".curate.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_LEDGER)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quarantine wrong-take / unrecognisable acquisitions.")
    parser.add_argument("--execute", action="store_true",
                        help="actually quarantine (default is a dry run)")
    args = parser.parse_args()

    cache = FeatureCache()
    rows = find_wrong_versions(cache)
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    print(f"{len(rows)} unverified acquisition(s): "
          + " · ".join(f"{k} {v}" for k, v in sorted(by_kind.items())) + "\n")
    for r in rows:
        c = "  n/a" if r["confidence"] is None else f"{r['confidence']:5.2f}"
        print(f" {c}  [{r['kind']}] {str(r['track'])[:46]!r} — {str(r['artist'])[:24]!r}")
        print(f"          src: {str(r['source'])[:66]}")
        print(f"          {r['reason']}")

    if not rows:
        print("\nnothing to quarantine.")
        return 0
    if not args.execute:
        print(f"\nDRY RUN — nothing changed. Re-run with --execute to quarantine "
              f"these {len(rows)} tracks (a backup is taken first).")
        return 0

    from src.store.backup import backup
    dest = backup(_DATA / "feature_cache.db", _SPECTROGRAMS, _ROOT / "backups")
    print(f"\nbacked up: {dest}")

    reasons = {r["id"]: f"quarantined {r['kind']} — {r['reason']}" for r in rows}
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
    print("NEXT: retrain clusters, rebuild marts, re-export gold, re-run both audits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
