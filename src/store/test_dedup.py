"""
test_dedup.py — pure near-duplicate detection (Epic O / D-28), synthetic.

No cache, no DB, no audio: DedupRecord fixtures only. Verifies the ONE definition
of "duplicate" the cache and the audit both import — precision-biased.
"""
from __future__ import annotations

from .dedup import (
    DedupRecord,
    duplicate_of_map,
    find_duplicate_clusters,
    normalize_artist,
    normalize_title,
)


def test_normalize_title_strips_qualifiers_keeps_distinct():
    n = normalize_title
    # same recording under different release tags → one normalized title
    assert n("Bohemian Rhapsody - Remastered 2011") == n("Bohemian Rhapsody")
    assert n("Starlight (Live at Wembley)") == n("Starlight")
    assert n("Time - 2019 Remaster") == n("Time")
    assert n("Señorita (feat. X)") == n("senorita")           # diacritics + feat
    # a plain-word " - " subtitle is NOT a version qualifier → stays distinct
    assert n("Song - The Sequel") != n("Song")
    assert normalize_title(None) == "" and normalize_title("") == ""
    assert normalize_artist("Beyoncé") == "beyonce"


def _rec(tid, title="Hysteria", artist="Muse", dur=210000, vec=None, cached=False):
    return DedupRecord(tid, title, artist, dur, vec, cached)


def test_exact_name_artist_within_window_clusters():
    clusters = find_duplicate_clusters([
        _rec("a", dur=210000), _rec("b", dur=210800),   # 0.8s apart → dupe
        _rec("c", title="Uprising")])                    # different song → alone
    assert len(clusters) == 1
    assert clusters[0].members == ("a", "b")


def test_outside_duration_window_is_not_a_dupe():
    # same name+artist but 30s apart → distinct takes, NOT merged (precision)
    clusters = find_duplicate_clusters([_rec("a", dur=210000), _rec("b", dur=240000)])
    assert clusters == []


def test_different_artist_same_title_is_not_a_dupe():
    clusters = find_duplicate_clusters([
        _rec("a", title="Hurt", artist="Nine Inch Nails"),
        _rec("b", title="Hurt", artist="Johnny Cash")])
    assert clusters == []


def test_canonical_prefers_cached_then_longer_then_smallest_id():
    # b is cached → canonical even though a sorts first / is longer
    c = find_duplicate_clusters([_rec("a", dur=211000), _rec("b", dur=210000, cached=True)])
    assert c[0].canonical_id == "b"
    # neither cached → longer duration wins
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


def test_duplicate_of_map_and_empty_titles():
    dmap = duplicate_of_map([_rec("a", dur=210000, cached=True), _rec("b", dur=210500)])
    assert dmap == {"b": "a"}                                 # non-canonical → canonical
    assert duplicate_of_map([_rec("a", title=""), _rec("b", title="")]) == {}  # no title, no cluster
