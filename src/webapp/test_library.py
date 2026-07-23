"""
test_library.py — synthetic tests for the Library catalog (Epic H1 / P3.3).

Covers the pure view logic (search / sort / dedup annotation / 'mine' overlay /
why-N explainer) and the cache.library_rows() projection. Synthetic only —
no real API, no audio (ground rule #5).
"""

from __future__ import annotations

import pytest

from ..store.cache import FeatureCache
from . import library

_ROWS = [
    {"id": "a", "name": "Zephyr", "artist": "Beck", "popularity": 40,
     "duplicate_of": None, "analyzed": True, "tempo": 120.0, "energy": 0.3,
     "brightness": 2000.0, "art": None},
    {"id": "b", "name": "Anthem", "artist": "Aviv", "popularity": 90,
     "duplicate_of": None, "analyzed": True, "tempo": 90.0, "energy": 0.5,
     "brightness": 1500.0, "art": None},
    {"id": "c", "name": "anthem (live)", "artist": "Aviv", "popularity": 10,
     "duplicate_of": "b", "analyzed": False, "tempo": None, "energy": None,
     "brightness": None, "art": None},
]


def test_search_matches_name_and_artist_case_insensitive():
    v = library.library_view(_ROWS, q="aviv")
    assert {r["id"] for r in v["rows"]} == {"b", "c"}
    v2 = library.library_view(_ROWS, q="ANTHEM")
    assert {r["id"] for r in v2["rows"]} == {"b", "c"}


def test_sort_name_asc_and_popularity_desc():
    asc = library.library_view(_ROWS, sort="name", order="asc")["rows"]
    assert [r["id"] for r in asc] == ["b", "c", "a"]  # "anthem" < "anthem (live)" < "zephyr"
    pop = library.library_view(_ROWS, sort="popularity", order="desc")["rows"]
    assert [r["id"] for r in pop] == ["b", "a", "c"]


def test_numeric_nones_sort_last_in_both_orders():
    for order in ("asc", "desc"):
        ids = [r["id"] for r in
               library.library_view(_ROWS, sort="tempo", order=order)["rows"]]
        assert ids[-1] == "c"  # unanalyzed (tempo None) never floats above real values


def test_mine_overlay_filters_to_viewer_set():
    v = library.library_view(_ROWS, mine_ids={"a"})
    assert [r["id"] for r in v["rows"]] == ["a"]
    assert v["total"] == 3 and v["shown"] == 1  # honesty numbers intact


def test_analyzed_only_and_counts():
    v = library.library_view(_ROWS, analyzed_only=True)
    assert {r["id"] for r in v["rows"]} == {"a", "b"}
    assert v["total"] == 3 and v["analyzed"] == 2


def test_annotate_dupes_resolves_canonical_name():
    rows = library.annotate_dupes([dict(r) for r in _ROWS])
    same = {r["id"]: r["same_as"] for r in rows}
    assert same["c"] == "Anthem" and same["a"] is None and same["b"] is None


def test_why_n_derives_from_top_limit():
    txt = library.why_n_analyzed(39, top_limit=50)
    assert "39" in txt and "50" in txt and "150" in txt  # 50 × 3 ceiling


def test_bad_sort_falls_back_to_name():
    v = library.library_view(_ROWS, sort="bogus")
    assert v["sort"] == "name"


@pytest.fixture
def cache(tmp_path):
    return FeatureCache(url=f"sqlite:///{tmp_path / 'lib.db'}")


def test_library_rows_projects_meta_and_features(cache):
    cache.remember_meta([
        {"spotify_track_id": "t1", "track_name": "Song One", "artist_names": "X",
         "popularity": 55, "album_image_url": "http://img/1"},
        {"spotify_track_id": "t2", "track_name": "Song Two", "artist_names": "Y"},
    ])
    cache.upsert("t1", {"tempo_bpm": 128.0, "rms_mean": 0.2,
                        "spectral_centroid_mean": 2100.0})
    rows = {r["id"]: r for r in cache.library_rows()}
    assert set(rows) == {"t1", "t2"}
    assert rows["t1"]["analyzed"] is True and rows["t1"]["tempo"] == 128.0
    assert rows["t1"]["popularity"] == 55 and rows["t1"]["art"] == "http://img/1"
    assert rows["t2"]["analyzed"] is False and rows["t2"]["tempo"] is None


# ── route matrix: /library is PUBLIC (D-18), /song + /spectrogram flipped ─────
from . import config  # noqa: E402


@pytest.fixture
def rclient():
    from fastapi.testclient import TestClient

    from .app import create_app
    return TestClient(create_app())


def _seed_session(taste=None, guest=False):
    from .app import _signer, _store
    sid = _store.new()
    sess = _store.get(sid)
    if guest:
        sess["is_guest"] = True
    else:
        sess["token"] = {"access_token": "x"}
    if taste is not None:
        sess["taste"] = taste
    return _signer.sign(sid)


def _seed_route_cache(tmp_path):
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'librt.db'}")
    tc.remember_meta([
        {"spotify_track_id": "aaaaaaaa", "track_name": "Zephyr", "artist_names": "Beck"},
        {"spotify_track_id": "bbbbbbbb", "track_name": "Anthem", "artist_names": "Aviv"},
    ])
    tc.upsert("aaaaaaaa", {"tempo_bpm": 120.0, "rms_mean": 0.3,
                           "spectral_centroid_mean": 2000.0})
    return tc


_RTASTE = {"range_ids": {"short_term": ["aaaaaaaa"]}}


def test_library_public_for_anon(rclient, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache",
                        lambda: _seed_route_cache(tmp_path))
    r = rclient.get("/library")  # no cookie at all
    assert r.status_code == 200 and "Zephyr" in r.text
    assert 'href="/library?tab=mine"' not in r.text  # no personal tab for anon


def test_library_mine_tab_for_viewer(rclient, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache",
                        lambda: _seed_route_cache(tmp_path))
    rclient.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_RTASTE, guest=True))
    r = rclient.get("/library?tab=mine")
    assert r.status_code == 200 and "Zephyr" in r.text and "Anthem" not in r.text


def test_library_search_filters(rclient, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache",
                        lambda: _seed_route_cache(tmp_path))
    r = rclient.get("/library?q=anthem")
    assert "Anthem" in r.text and "Zephyr" not in r.text


def test_library_provenance_glyph_and_legend(rclient, monkeypatch, tmp_path):
    # Q2/D-51: the Src column shows ✓ for a recorded source and the legend renders;
    # the seed cache has no provenance for Anthem → its ∅ glyph appears too.
    def _cache():
        tc = _seed_route_cache(tmp_path)
        tc.remember_provenance(spotify_track_id="aaaaaaaa", match_confidence=0.86)
        return tc
    monkeypatch.setattr("src.webapp.app._feature_cache", _cache)
    r = rclient.get("/library")
    assert r.status_code == 200
    assert "prov-glyph" in r.text and ">Src<" in r.text          # column + glyph rendered
    assert "audio-source provenance" in r.text                   # the legend caption


def test_song_public_and_bad_id_redirects(rclient, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache",
                        lambda: _seed_route_cache(tmp_path))
    ok = rclient.get("/song/aaaaaaaa")  # anon, valid analyzed id
    assert ok.status_code == 200 and "Zephyr" in ok.text
    bad = rclient.get("/song/../etc", follow_redirects=False)
    assert bad.status_code in (303, 307, 404)  # junk id never 200s the deep-dive
