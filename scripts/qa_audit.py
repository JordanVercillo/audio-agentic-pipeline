"""
qa_audit.py — the Epic-Q regression sweep over LIVE data (QA1).

Every bug fixed in the provenance/QA epic gets a standing check here, because
almost none of them were caught by the unit suite: they only appeared when the
feature was actually used. A synthetic test proves the code does what it says;
this proves the CORPUS is what we claim.

    uv run python scripts/qa_audit.py            # the pass/fail table
    uv run python scripts/qa_audit.py --json     # machine-readable

Exit code 1 if any check FAILS, so it can gate a release. NOTE-level findings
never fail the run — they are the honest tail (legitimately long DJ mixes, a
pre-gate corpus that today's stricter bar would not re-admit).

Read-only: no downloads, no writes, no network. Complements warehouse-audit
(schema/marts) and app-verify (the running system) — this one is about whether
the audio behind the numbers is the audio we say it is.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.ingestion.match_gate import (  # noqa: E402
    confident_match,
    implausible_duration,
    title_affinity,
)
from src.store.cache import FeatureCache  # noqa: E402

_MARTS = _ROOT / "data" / "marts"

PASS, FAIL, NOTE = "PASS", "FAIL", "NOTE"


def _result(status: str, headline: str, detail: Any = None) -> dict:
    return {"status": status, "headline": headline, "detail": detail or []}


# ── A1: DJ sets stored as songs ──────────────────────────────────────────────
def check_duration_sanity(cache: FeatureCache) -> dict:
    """No track's acquired audio may be implausibly longer than Spotify's own
    length for it. 19 tracks once carried mix-length audio, up to 37x."""
    bad = []
    for r in cache.all_provenance():
        tid = r["spotify_track_id"]
        meta = cache.get_meta(tid) or {}
        expected = (meta.get("duration_ms") or 0) / 1000.0
        got = r.get("youtube_duration_s")
        if implausible_duration(got, expected):
            bad.append({"track": meta.get("track_name"), "id": tid,
                        "acquired_s": got, "expected_s": round(expected, 1),
                        "ratio": round((got or 0) / expected, 1) if expected else None})
    if bad:
        return _result(FAIL, f"{len(bad)} track(s) carry implausibly long audio", bad[:10])
    return _result(PASS, "no track's audio is implausibly longer than its Spotify length")


# ── A2 / A3: wrong songs, and the recheck being repeatable ───────────────────
def _is_machine_match(row: dict) -> bool:
    """Was this audio CHOSEN by the matcher? A D-56 manual repair was chosen by
    the owner, who is better evidence than any heuristic — and an upload has no
    candidate title at all (the constant "Owner-supplied audio file"), so
    judging it by title affinity would report the most trustworthy source in
    the corpus as a wrong song. Caught by this sweep on its first run."""
    return not str(row.get("matcher_version") or "").startswith("manual")


def check_title_affinity(cache: FeatureCache) -> dict:
    """Every MACHINE-CHOSEN acquisition must still look like the song it claims.
    This reuses the quarantine's own function, so "would the gate reject it?"
    and "did we quarantine it?" can never drift apart."""
    bad = []
    skipped = 0
    for r in cache.all_provenance():
        tid = r["spotify_track_id"]
        meta = cache.get_meta(tid) or {}
        if not _is_machine_match(r):
            skipped += 1
            continue
        if not meta.get("track_name") or not r.get("youtube_title"):
            continue
        if not title_affinity(meta.get("track_name"), meta.get("artist_names"),
                              r.get("youtube_title"), r.get("channel")):
            bad.append({"track": meta.get("track_name"), "id": tid,
                        "got": r.get("youtube_title"), "channel": r.get("channel")})
    if bad:
        return _result(FAIL, f"{len(bad)} acquisition(s) do not look like their track", bad[:10])
    return _result(PASS, "every machine-chosen acquisition still passes the "
                         f"affinity check ({skipped} owner-supplied skipped)")


def check_confident_match(cache: FeatureCache) -> dict:
    """How much of the corpus would today's STRICTER gate re-admit? Informational:
    most rows predate the gate, and a legitimate remix or label upload can fail
    it without being wrong. A falling number between runs is the signal."""
    total = graded = strict = 0
    for r in cache.all_provenance():
        total += 1
        meta = cache.get_meta(r["spotify_track_id"]) or {}
        if not _is_machine_match(r):
            continue                      # owner-chosen: not the gate's business
        if not meta.get("track_name") or not r.get("youtube_title"):
            continue
        graded += 1
        cand = {"title": r.get("youtube_title"), "channel": r.get("channel"),
                "youtube_duration_s": r.get("youtube_duration_s")}
        if confident_match(meta.get("track_name"), meta.get("artist_names"), cand,
                           (meta.get("duration_ms") or 0) / 1000.0 or None):
            strict += 1
    pct = round(100.0 * strict / graded, 1) if graded else 0.0
    return _result(NOTE, f"{strict}/{graded} recorded acquisitions ({pct}%) would pass "
                         f"today's strict gate", {"total_rows": total})


# ── the provenance floor ─────────────────────────────────────────────────────
def check_provenance_coverage(cache: FeatureCache) -> dict:
    """Every canonical analyzed track must trace to a source. Since B2 the
    unvalidated are out of the aggregates, so this should read 100%: anything
    less means a track is shaping numbers without a verifiable origin."""
    analyzed = set(cache.all_features())
    canonical = analyzed - cache.twin_ids()
    validated = canonical & cache.source_validated_ids()
    missing = canonical - validated
    pct = round(100.0 * len(validated) / len(canonical), 1) if canonical else 0.0
    detail = {"canonical": len(canonical), "validated": len(validated),
              "withheld": len(missing)}
    if missing:
        return _result(NOTE, f"{len(validated)}/{len(canonical)} canonical analyzed "
                             f"({pct}%) have a source; {len(missing)} withheld", detail)
    return _result(PASS, f"all {len(canonical)} canonical analyzed tracks have a "
                         "recorded source (100%)", detail)


# ── B2: the exclusion actually reached the serving planes ────────────────────
def check_aggregate_exclusion(cache: FeatureCache) -> dict:
    """A withheld track must not appear in any plane the app aggregates over.
    Withholding it from DISPLAY while its row still answers /explore is exactly
    the trap B2 exists to close (and O3's merge-only persistence bug before it)."""
    excluded = cache.excluded_from_aggregates()
    if not excluded:
        return _result(PASS, "nothing is excluded, so nothing can leak")
    leaks = []
    try:
        import pandas as pd
    except ImportError:
        return _result(NOTE, "pandas unavailable — mart planes not checked")
    for mart in ("track_perceptual", "track_card"):
        path = _MARTS / f"{mart}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["spotify_track_id"])
        hit = excluded & set(df["spotify_track_id"])
        if hit:
            leaks.append({"mart": mart, "n": len(hit), "ids": sorted(hit)[:5]})
    rows = cache.perceptual_rows() if hasattr(cache, "perceptual_rows") else None
    if rows is not None:
        hit = excluded & set(rows)
        if hit:
            leaks.append({"table": "track_perceptual", "n": len(hit),
                          "ids": sorted(hit)[:5]})
    if leaks:
        return _result(FAIL, "excluded tracks are still in a serving plane", leaks)
    return _result(PASS, f"all {len(excluded)} excluded tracks are absent from "
                         "every serving plane")


# ── A5: a repair must refresh the derived planes ─────────────────────────────
def check_plane_coherence(cache: FeatureCache) -> dict:
    """The feature store, the perceptual plane and the analyst card must agree
    on WHICH tracks exist. A repair that updated features but left the derived
    planes stale is invisible until someone asks /explore for a number."""
    try:
        import pandas as pd
    except ImportError:
        return _result(NOTE, "pandas unavailable — planes not compared")
    expected = set(cache.all_features()) - cache.excluded_from_aggregates()
    detail = {"expected": len(expected)}
    mismatch = []
    for mart in ("track_perceptual", "track_card"):
        path = _MARTS / f"{mart}.parquet"
        if not path.exists():
            mismatch.append({"mart": mart, "error": "missing"})
            continue
        ids = set(pd.read_parquet(path, columns=["spotify_track_id"])["spotify_track_id"])
        detail[mart] = len(ids)
        # the card/plane may legitimately drop rows with incomplete features,
        # so only EXTRA ids (present but not expected) are a coherence break
        extra = ids - expected
        if extra:
            mismatch.append({"mart": mart, "unexpected": len(extra),
                             "ids": sorted(extra)[:5]})
    if mismatch:
        return _result(FAIL, "the derived planes disagree with the feature store",
                       mismatch)
    return _result(PASS, "feature store, perceptual plane and analyst card agree",
                   detail)


# ── B1: the live worker and the runner share ONE gate ────────────────────────
def check_shared_gate() -> dict:
    """The worker's acquisition path must refuse a DJ set. This is the check
    that would have caught B1: the runner had guards for a whole session while
    the path every real login uses had none. Behavioural, not introspective —
    it drives default_acquire with a rigged search and asserts nothing is
    downloaded. No network: the search is replaced in-process."""
    from unittest.mock import patch

    from src.store.extractor import default_acquire
    downloads: list = []
    dj_set = [{"url": "https://y/mix", "title": "2 Hour Bassline Mix",
               "channel": "SomeDJ", "score": 25, "youtube_duration_s": 7396.0}]
    wrong_song = [{"url": "https://y/x", "title": "A Totally Different Tune",
                   "channel": "Someone", "score": 25, "youtube_duration_s": 205.0}]
    failures = []
    with patch("src.ingestion.audio_downloader.resolve_youtube_candidates") as search, \
         patch("src.ingestion.audio_downloader.download_track_audio",
               side_effect=lambda *a, **k: downloads.append(a)):
        for label, candidates in (("DJ set", dj_set), ("wrong song", wrong_song)):
            search.return_value = candidates
            path, match = default_acquire("t", "WGTF?", "Riordan",
                                          Path("."), 207.0)
            if path is not None or not (match or {}).get("_rejected"):
                failures.append(f"the worker ACCEPTED a {label}")
    if downloads:
        failures.append(f"{len(downloads)} download(s) started despite rejection")
    if failures:
        return _result(FAIL, "the live worker's acquisition path is not guarded",
                       failures)
    return _result(PASS, "the live worker refuses a DJ set and a wrong-title "
                         "candidate before downloading")


# ── A4: the ffmpeg that silently killed every repair ─────────────────────────
def check_mp3_encoder() -> dict:
    """A repair once failed at conversion on every attempt because Anaconda's
    ffmpeg — no libmp3lame — came first on the webapp's PATH. Ask the binary,
    since the name tells you nothing."""
    from src.ingestion.audio_downloader import ffmpeg_location
    loc = ffmpeg_location()
    if not loc:
        return _result(FAIL, "no ffmpeg with libmp3lame found — every acquisition "
                             "will fail at conversion")
    return _result(PASS, f"an MP3-capable ffmpeg resolves ({loc})")


# ── A6: the owner upload cap ─────────────────────────────────────────────────
def check_upload_cap() -> dict:
    """D-45's 20 MB cap was specced for PUBLIC uploads; D-56 repair is
    owner-only, and a lossless master does not fit in 20 MB."""
    from src.store.repair import MAX_UPLOAD_BYTES
    mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    if mb < 100:
        return _result(FAIL, f"owner upload cap is {mb} MB — lossless masters "
                             "will not fit")
    return _result(PASS, f"owner upload cap is {mb} MB (lossless masters fit)")


CHECKS: list[tuple[str, str, Callable]] = [
    ("A1", "duration_sanity", check_duration_sanity),
    ("A2/A3", "title_affinity", check_title_affinity),
    ("A2+", "confident_match", check_confident_match),
    ("Q", "provenance_coverage", check_provenance_coverage),
    ("B2", "aggregate_exclusion", check_aggregate_exclusion),
    ("A5", "plane_coherence", check_plane_coherence),
    ("B1", "shared_gate", check_shared_gate),
    ("A4", "mp3_encoder", check_mp3_encoder),
    ("A6", "upload_cap", check_upload_cap),
]

_NEEDS_CACHE = {"duration_sanity", "title_affinity", "confident_match",
                "provenance_coverage", "aggregate_exclusion", "plane_coherence"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Epic-Q regression sweep over live data.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    cache = FeatureCache()
    results: dict[str, dict] = {}
    for tag, name, fn in CHECKS:
        try:
            results[name] = fn(cache) if name in _NEEDS_CACHE else fn()
        except Exception as exc:  # noqa: BLE001 — one broken check must not hide the rest
            results[name] = _result(FAIL, f"check raised {type(exc).__name__}: {exc}")
        results[name]["tag"] = tag

    failed = [n for n, r in results.items() if r["status"] == FAIL]
    if args.json:
        print(json.dumps({"results": results, "failed": failed}, indent=2, default=str))
        return 1 if failed else 0

    width = max(len(n) for n in results)
    print("\nEpic-Q QA sweep — live corpus\n" + "─" * 78)
    for tag, name, _ in CHECKS:
        r = results[name]
        mark = {PASS: "✓", FAIL: "✗", NOTE: "·"}[r["status"]]
        print(f" {mark} {r['status']:<4} [{tag:>5}] {name:<{width}}  {r['headline']}")
        if r["status"] == FAIL and r["detail"]:
            for row in (r["detail"] if isinstance(r["detail"], list) else [r["detail"]]):
                print(f"        └─ {row}")
    print("─" * 78)
    print(f"{len(failed)} failed · "
          f"{sum(1 for r in results.values() if r['status'] == PASS)} passed · "
          f"{sum(1 for r in results.values() if r['status'] == NOTE)} note\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
