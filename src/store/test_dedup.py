"""
test_dedup.py — pure near-duplicate detection (Epic O / D-28, inverted by O4).

No cache, no DB, no audio: DedupRecord fixtures only. Verifies the ONE definition
of "duplicate" the cache and the audit both import — precision-biased.
"""
from __future__ import annotations

import random

from .dedup import (
    DedupRecord,
    duplicate_of_map,
    find_disagreements,
    find_duplicate_clusters,
    normalize_artist,
    normalize_title,
    parse_title,
)


def _rec(tid, title="Hysteria", artist="Muse", dur=210000, vec=None, cached=False,
         artist_id=None):
    return DedupRecord(tid, title, artist, dur, vec, cached, artist_id)


# ── O4a: version-aware parsing ────────────────────────────────────────────────

def test_parse_title_extracts_version_and_drops_release():
    """THE O4 DOCTRINE INVERSION. Before O4 this asserted the opposite — that a
    live take normalized EQUAL to its studio original — because the rule stripped
    version qualifiers. The owner's rule is that different audio is a different
    track, so the qualifier is now EXTRACTED and compared, not discarded."""
    assert parse_title("Bohemian Rhapsody - Remastered 2011") == ("bohemian rhapsody", "")
    assert parse_title("Time - 2019 Remaster") == ("time", "")
    assert parse_title("Señorita (feat. X)") == ("senorita", "")
    # release packaging collapses; the VERSION does not
    assert parse_title("Starlight (Live at Wembley)") == ("starlight", "live at wembley")
    assert parse_title("Everchanging - Acoustic") == ("everchanging", "acoustic")
    assert parse_title("Fearless (Taylor's Version)")[1] != ""      # a re-recording splits
    assert parse_title(None) == ("", "") and parse_title("") == ("", "")
    assert normalize_title("Time - 2019 Remaster") == "time"        # the base, one definition
    assert normalize_artist("Beyoncé") == "beyonce"


def test_parse_title_keeps_a_non_qualifier_parenthetical():
    """The JOY bug: the old _PAREN_RE nuked EVERY parenthetical, so two different
    songs both normalized to "joy" and were kept apart only by their credit
    strings. Brackets are now stripped only when their content is a qualifier."""
    assert parse_title("JOY (If You Want)")[0] != parse_title("JOY (By My Side)")[0]
    assert parse_title("Shapes (Oh Will)") == ("shapes oh will", "")
    assert parse_title("Undone - The Sweater Song") == ("undone the sweater song", "")
    assert normalize_title("Song - The Sequel") != normalize_title("Song")


def test_merge_needs_tag_equality_not_tag_absence():
    """"It Gets Better - Forever Mix" ships on two releases and BOTH carry the
    tag — so the rule is tag EQUALITY. A tag-absence rule would refuse this real
    twin pair, and a strip-the-tag rule would merge the pair below."""
    both = [_rec("a", title="It Gets Better - Forever Mix", cached=True),
            _rec("b", title="It Gets Better - Forever Mix")]
    assert find_duplicate_clusters(both)[0].members == ("a", "b")
    assert find_duplicate_clusters([_rec("a", title="It Gets Better - Forever Mix"),
                                    _rec("b", title="It Gets Better")]) == []


def test_owner_rule_versions_never_merge_with_the_plain_take():
    """The owner's sentence, encoded: remix / live / acoustic / DJ-mixed are
    different audio and stay separate even at identical duration and artist."""
    for tag in ("Oppidan Remix", "Acoustic", "Live at Wembley", "Mixed",
                "Radio Edit", "KETTAMA MIX", "Sped Up"):
        pair = [_rec("a", title="Song", dur=200000),
                _rec("b", title=f"Song - {tag}", dur=200000)]
        assert find_duplicate_clusters(pair) == [], tag


# ── O4b: release-blind / credit-blind keying ──────────────────────────────────

def test_release_and_credit_differences_do_not_block_a_merge():
    """The owner's ask: the same recording on an album and on a single is ONE
    track, even when the single credits a guest the album does not."""
    a = DedupRecord("a", "Song - Deluxe Edition", "Band", 210000, None, True, "AID")
    b = DedupRecord("b", "Song", "Band, Guest", 210400, None, False, "AID")
    assert find_duplicate_clusters([a, b])[0].members == ("a", "b")


def test_credit_blind_merge_demands_a_tight_duration():
    """The "A Little Closer" hazard, measured live: a remix 6860 ms from its
    original, same primary_artist_id, differing credit strings — INSIDE the
    normal 7 s window. Once credit-blindness gives up the artist guard the
    version tag is the last one, so demand a tight, PRESENT duration match."""
    a = DedupRecord("a", "Song", "Band", 210000, None, False, "AID")
    b = DedupRecord("b", "Song", "Band, Remixer", 216860, None, False, "AID")
    assert find_duplicate_clusters([a, b]) == []
    c = DedupRecord("c", "Song", "Band, Remixer", 210400, None, False, "AID")
    assert find_duplicate_clusters([a, c])[0].members == ("a", "c")
    d = DedupRecord("d", "Song", "Band, Remixer", None, None, False, "AID")
    assert find_duplicate_clusters([a, d]) == []   # unknown duration is not a free pass


# ── O4c: duration-led candidate generation ────────────────────────────────────

def test_duration_led_pass_catches_spelling_and_spacing_variants():
    """Both real, both live in the corpus, and neither is reachable by title
    bucketing: "Airmaxes" shares no TOKEN with "Air Maxes"."""
    for t1, t2 in [("Here's Lookin At You, Kid", "Here's Looking At You, Kid"),
                   ("Air Maxes - KETTAMA MIX", "Airmaxes - KETTAMA Mix")]:
        c = find_duplicate_clusters([_rec("a", title=t1, dur=213977, cached=True),
                                     _rec("b", title=t2, dur=213977, cached=True)])
        assert c and c[0].members == ("a", "b"), t1


def test_duration_led_pass_refuses_a_differing_number():
    """Caught by the synthetic warehouse fixture, not by the corpus: "Club 0"
    and "Club 1" score 0.83 on difflib — above any floor loose enough to catch a
    real spelling variant. A number in a title is IDENTITY ("Part 1"/"Part 2"),
    so differing digits refuse regardless of similarity or equal duration."""
    for t1, t2 in [("Club 0", "Club 1"), ("Part 1", "Part 2"),
                   ("Untitled 3", "Untitled 4")]:
        assert find_duplicate_clusters([_rec("a", title=t1, dur=200000),
                                        _rec("b", title=t2, dur=200000)]) == [], t1
    # ...while matching numbers are still allowed to be a spelling variant
    c = find_duplicate_clusters([_rec("a", title="Blink 182 Song", dur=200000),
                                 _rec("b", title="Blink182 Song", dur=200000)])
    assert c and c[0].members == ("a", "b")


def test_duration_led_pass_holds_the_line():
    # different songs that merely collide on duration
    assert find_duplicate_clusters([_rec("a", title="Know Myself", dur=200000),
                                    _rec("b", title="Morning Miggy", dur=200000)]) == []
    # a coincidence across artists is never a candidate
    assert find_duplicate_clusters([_rec("a", title="Numb", artist="Linkin Park", dur=200000),
                                    _rec("b", title="Numb", artist="KREAM", dur=200000)]) == []
    # equal durations do NOT excuse a different version tag
    assert find_duplicate_clusters([_rec("a", title="Song", dur=200000),
                                    _rec("b", title="Song - Acoustic", dur=200000)]) == []


def test_clusters_are_deterministic_under_input_permutation():
    """Two keyings share ONE union-find, so the result must be the connected
    components — not an artifact of iteration order."""
    recs = [_rec("a", dur=210000, cached=True), _rec("b", dur=210400),
            _rec("c", title="Hysterya", dur=210000), _rec("d", title="Uprising")]
    ref = find_duplicate_clusters(recs)
    for seed in range(20):
        shuffled = recs[:]
        random.Random(seed).shuffle(shuffled)
        assert find_duplicate_clusters(shuffled) == ref


# ── the pre-O4 invariants that still hold ─────────────────────────────────────

def test_exact_name_artist_within_window_clusters():
    clusters = find_duplicate_clusters([
        _rec("a", dur=210000), _rec("b", dur=210800),   # 0.8s apart → dupe
        _rec("c", title="Uprising")])                    # different song → alone
    assert len(clusters) == 1
    assert clusters[0].members == ("a", "b")


def test_outside_duration_window_is_not_a_dupe():
    clusters = find_duplicate_clusters([_rec("a", dur=210000), _rec("b", dur=240000)])
    assert clusters == []


def test_different_artist_same_title_is_not_a_dupe():
    clusters = find_duplicate_clusters([
        _rec("a", title="Hurt", artist="Nine Inch Nails"),
        _rec("b", title="Hurt", artist="Johnny Cash")])
    assert clusters == []


def test_canonical_prefers_cached_then_longer_then_smallest_id():
    c = find_duplicate_clusters([_rec("a", dur=211000), _rec("b", dur=210000, cached=True)])
    assert c[0].canonical_id == "b"
    c2 = find_duplicate_clusters([_rec("a", dur=210000), _rec("z", dur=213000)])
    assert c2[0].canonical_id == "z"


def test_cosine_tiebreak_rejects_distant_pair_only_when_both_cached():
    near_a = _rec("a", vec=[1.0, 0.0, 0.0], cached=True)
    near_b = _rec("b", vec=[0.99, 0.01, 0.0], cached=True)
    assert find_duplicate_clusters([near_a, near_b])[0].members == ("a", "b")  # merged
    far_a = _rec("a", vec=[1.0, 0.0, 0.0], cached=True)
    far_b = _rec("b", vec=[0.0, 1.0, 0.0], cached=True)
    assert find_duplicate_clusters([far_a, far_b]) == []                       # rejected
    # one side uncached → no vector → tiebreak inert, metadata decides (merged)
    assert find_duplicate_clusters([far_a, _rec("b", cached=False)])[0].members == ("a", "b")


def test_canonicalize_ids_order_and_collapse():
    from .dedup import canonicalize_ids, canonicalize_range_ids
    dmap = {"twin1": "canon1", "twin2": "canon2"}
    assert canonicalize_ids(["a", "twin1", "canon1", "b"], dmap) == ["a", "canon1", "b"]
    assert canonicalize_ids(["canon2", "twin2"], dmap) == ["canon2"]
    assert canonicalize_ids(["twin1"], dmap) == ["canon1"]     # twin-first keeps rank
    assert canonicalize_ids([], dmap) == []
    r = canonicalize_range_ids({"short_term": ["twin1", "x"],
                                "long_term": ["canon1", "twin1"]}, dmap)
    assert r == {"short_term": ["canon1", "x"], "long_term": ["canon1"]}


def test_duplicate_of_map_and_empty_titles():
    dmap = duplicate_of_map([_rec("a", dur=210000, cached=True), _rec("b", dur=210500)])
    assert dmap == {"b": "a"}                                 # non-canonical → canonical
    assert duplicate_of_map([_rec("a", title=""), _rec("b", title="")]) == {}


def test_dedup_record_stays_constructible_the_way_the_audit_builds_it():
    """The uv-isolated audit exec_module's this file and builds records with FOUR
    keywords; the cache builds them with SEVEN positionals. A new field that is
    not appended-with-a-default breaks the audit at import time."""
    r = DedupRecord(track_id="x", title="Song", artist="Band", duration_ms=1000)
    assert r.vector is None and r.is_cached is False and r.primary_artist_id is None
    assert find_duplicate_clusters([r]) == []


# ── O4d: the acoustic-disagreement detector ───────────────────────────────────

def test_a_disagreement_is_never_also_a_duplicate():
    """THE tripwire for the regression DEDUP_DISAGREEMENT exists to catch: the
    merger and the detector share ONE threshold, so their outputs must be
    disjoint for any input. If they drift, a wrong acquisition could be merged
    away and stop being visible."""
    recs = [_rec("a", vec=[1.0, 0.0, 0.0], cached=True),
            _rec("b", vec=[0.6, 0.8, 0.0], cached=True),     # cos 0.60 → refuses
            _rec("c", vec=[0.99, 0.01, 0.0], cached=True)]   # cos ~1.0 → merges
    merged = {frozenset((d, c)) for d, c in duplicate_of_map(recs).items()}
    dis = {frozenset((x.track_id_a, x.track_id_b)) for x in find_disagreements(recs)}
    assert dis and merged and not (dis & merged)


def test_find_disagreements_is_silent_when_it_cannot_know():
    """Never accuses on half the evidence, and never treats a genuine version
    difference as a defect."""
    assert find_disagreements([_rec("a", vec=[1.0, 0.0, 0.0], cached=True),
                               _rec("b", cached=False)]) == []
    assert find_disagreements([_rec("a", title="Song", vec=[1.0, 0.0], cached=True),
                               _rec("b", title="Song - Acoustic", vec=[0.0, 1.0],
                                    cached=True)]) == []


def test_disagreement_pair_identity_is_stable_and_sorted():
    recs = [_rec("z", vec=[1.0, 0.0], cached=True), _rec("a", vec=[0.0, 1.0], cached=True)]
    d = find_disagreements(recs)
    assert len(d) == 1 and (d[0].track_id_a, d[0].track_id_b) == ("a", "z")
    assert d[0].duration_delta_ms == 0 and d[0].z_cosine < 0.95
