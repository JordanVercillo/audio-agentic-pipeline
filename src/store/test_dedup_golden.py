"""
test_dedup_golden.py — QA-2 layer 4: the owner's rule, encoded over REAL pairs.

Every case below is an actual pair from the live corpus, transcribed as literal
metadata so the whole set runs in CI with no database. The rule it encodes is
the owner's sentence of 2026-07-24:

    "If a track is in a separate album or single they should be treated as one.
     The only difference should be if there is different audio for a different
     version — a remix or live version, acoustic, etc."

MUST_SPLIT is the half that matters. Before O4 these pairs were kept apart only
INCIDENTALLY — by a credited remixer changing the artist string, or by a duration
gap — while the title normalizer actively threw away the qualifier that should
have decided it. Two of them ("Air Maxes", "Everchanging") were separated by
nothing but duration; a remix of the same length credited identically would have
merged, inheriting the original's features and a terminal `done` job.

A corpus-wide sweep at the bottom re-runs the rule over the real database when
one is present, and skips on CI (data/ is gitignored).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .dedup import DedupRecord, find_duplicate_clusters, parse_title

_ROOT = Path(__file__).resolve().parents[2]


def _r(tid, title, artist, dur, *, artist_id=None, cached=True):
    return DedupRecord(tid, title, artist, dur, None, cached, artist_id)


# (label, record_a, record_b) — every pair observed in the live corpus.
MUST_SPLIT = [
    ("remix, credited remixer",
     _r("a", "A Little Closer", "Diffrent", 175208, artist_id="AID"),
     _r("b", "A Little Closer - Oppidan Remix", "Diffrent, Oppidan", 182068,
        artist_id="AID")),
    ("DJ mix, IDENTICAL artist string — duration was the only pre-O4 guard",
     _r("a", "Air Maxes", "KETTAMA, Shady Nasty, Fred again..", 181172),
     _r("b", "Air Maxes - KETTAMA MIX", "KETTAMA, Shady Nasty, Fred again..", 213977)),
    ("acoustic take, IDENTICAL artist string",
     _r("a", "Everchanging", "Rise Against", 227026),
     _r("b", "Everchanging - Acoustic", "Rise Against", 261906)),
    ("remix, credited remixer",
     _r("a", "Low Again", "BOVSKI", 127123),
     _r("b", "Low Again - Niall T Remix", "BOVSKI, Niall T", 152228)),
    ("remix, neither side analyzed",
     _r("a", "NOW IT'S GONE", "IN PARALLEL", 143184, cached=False),
     _r("b", "NOW IT'S GONE - DIFFRENT REMIX", "IN PARALLEL, Diffrent", 178344,
        cached=False)),
    ("remix where the original's duration is UNKNOWN",
     _r("a", "Opalite", "Taylor Swift", None),
     _r("b", "Opalite - BUNT. Remix", "Taylor Swift, BUNT.", 212766)),
    ("remix of a title carrying a real parenthetical subtitle",
     _r("a", "Shapes (Oh Will)", "Sammy Virji", 317927),
     _r("b", "Shapes (Oh Will) - Oppidan Remix", "Sammy Virji, Oppidan", 265000)),
    # Not a version at all — two DIFFERENT songs. The pre-O4 paren strip
    # normalized both to "joy"; only the credit strings kept them apart.
    ("two different songs sharing a bracketed-subtitle stem",
     _r("a", "JOY (If You Want)", "Joy Anonymous, Champion", 235316),
     _r("b", "JOY (By My Side)", "Joy Anonymous, Sammy Virji", 222675)),
    # The owner's 2026-07-24 call: a continuous DJ "- Mixed" edit is different
    # audio, so it splits like a remix.
    ("continuous DJ mix vs the standalone release",
     _r("a", "Whippet (Sweetie Irie Dub)", "Interplanetary Criminal", 200000),
     _r("b", "Whippet (Sweetie Irie Dub) - Mixed", "Interplanetary Criminal", 332000)),
]

MUST_MERGE = [
    ("single release vs album release",
     _r("a", "Dani California", "Red Hot Chili Peppers", 282160),
     _r("b", "Dani California", "Red Hot Chili Peppers", 282160)),
    ("single vs album, Nowhere Generation",
     _r("a", "Talking To Ourselves", "Rise Against", 204160),
     _r("b", "Talking To Ourselves", "Rise Against", 204160)),
    # The tag is on BOTH sides — proof the rule is tag EQUALITY, not absence.
    ("one MIXED version shipped on two releases",
     _r("a", "It Gets Better - Forever Mix", "KETTAMA", 252767),
     _r("b", "It Gets Better - Forever Mix", "KETTAMA", 252767)),
    ("compilation vs original album",
     _r("a", "Surrender", "Billy Talent", 246600),
     _r("b", "Surrender", "Billy Talent", 246600)),
    ("single vs AM",
     _r("a", "Knee Socks", "Arctic Monkeys", 257563),
     _r("b", "Knee Socks", "Arctic Monkeys", 257563)),
    # O4c: title bucketing structurally cannot reach either of these.
    ("spelling variant at identical duration",
     _r("a", "Here's Lookin At You, Kid", "The Gaslight Anthem", 216040),
     _r("b", "Here's Looking At You, Kid", "The Gaslight Anthem", 216040)),
    ("spacing variant at identical duration, same version tag",
     _r("a", "Air Maxes - KETTAMA MIX", "KETTAMA, Shady Nasty, Fred again..", 213977),
     _r("b", "Airmaxes - KETTAMA Mix", "KETTAMA, Shady Nasty, Fred again..", 213977)),
    ("remaster of the same performance",
     _r("a", "Time", "Muse", 240000),
     _r("b", "Time - 2019 Remaster", "Muse", 240200)),
]


@pytest.mark.parametrize("label,a,b", MUST_SPLIT,
                         ids=[c[0][:40] for c in MUST_SPLIT])
def test_different_audio_stays_separate(label, a, b):
    clusters = find_duplicate_clusters([a, b])
    assert clusters == [], (
        f"{label}: {a.title!r} and {b.title!r} were merged — the owner's rule is "
        "that different audio is a different track")


@pytest.mark.parametrize("label,a,b", MUST_MERGE,
                         ids=[c[0][:40] for c in MUST_MERGE])
def test_same_recording_collapses_to_one(label, a, b):
    clusters = find_duplicate_clusters([a, b])
    assert len(clusters) == 1 and clusters[0].members == ("a", "b"), (
        f"{label}: {a.title!r} and {b.title!r} stayed separate — a release "
        "difference must never split one recording")


def test_the_split_cases_are_split_by_the_TAG_not_by_luck():
    """The point of O4a. Pre-O4 these pairs were kept apart by a credit string or
    a duration gap — incidental guards. Assert the version tag itself now
    differs, so the split survives an identical artist string and an identical
    duration."""
    for label, a, b in MUST_SPLIT[:7]:
        ta, tb = parse_title(a.title)[1], parse_title(b.title)[1]
        assert ta != tb, f"{label}: both sides parse to version tag {ta!r}"
    # ...and prove it directly: same artist, same duration, still split.
    twin_dur = [_r("a", "Everchanging", "Rise Against", 227026),
                _r("b", "Everchanging - Acoustic", "Rise Against", 227026)]
    assert find_duplicate_clusters(twin_dur) == []


# ── the live-corpus sweep (skips on CI: data/ is gitignored) ─────────────────
_DB = _ROOT / "data" / "feature_cache.db"
live_corpus = pytest.mark.skipif(not _DB.exists(), reason="no local corpus")


@live_corpus
def test_live_corpus_has_no_version_pair_merged():
    """Sweep the real corpus: no flagged twin pair may differ in version tag.
    The literal cases above cannot see a pair nobody has looked at yet."""
    from .cache import FeatureCache

    cache = FeatureCache()
    metas = cache.all_meta()
    offenders = []
    for twin, canon in cache.duplicate_flags().items():
        tt = parse_title((metas.get(twin) or {}).get("track_name"))[1]
        tc = parse_title((metas.get(canon) or {}).get("track_name"))[1]
        if tt != tc:
            offenders.append((twin, tt, canon, tc))
    assert not offenders, f"merged pairs with differing version tags: {offenders}"


@live_corpus
def test_live_corpus_disagreements_are_not_also_merged():
    """The O4d/merger threshold cannot drift apart on real data either."""
    from .cache import FeatureCache

    cache = FeatureCache()
    flags = cache.duplicate_flags()
    merged = {frozenset((d, c)) for d, c in flags.items()}
    dis = {frozenset((d["track_id_a"], d["track_id_b"]))
           for d in cache.acoustic_disagreements()}
    assert not (dis & merged)
