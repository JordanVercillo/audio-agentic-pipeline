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


def test_queue_state_tells_coming_apart_from_stopped():
    # The catalog used to render "analyzing…" for ANY unanalyzed track, so 40+
    # permanently-failed tracks advertised work that had already stopped.
    rows = [{"id": "live", "analyzed": False}, {"id": "dead", "analyzed": False},
            {"id": "retry", "analyzed": False}, {"id": "never", "analyzed": False},
            {"id": "done", "analyzed": True}]
    states = {"live": ("queued", 1), "dead": ("failed", 3), "retry": ("failed", 1)}
    got = {r["id"]: r["queue_state"]
           for r in library.annotate_queue_state(rows, states, max_attempts=3)}
    assert got["live"] == "analyzing"        # genuinely in flight
    assert got["dead"] == "no_source"        # dead-lettered: enqueue never retries
    # Under the cap a retry IS coming (the worker re-queues these now), but the
    # track is not in flight this second — and calling it "analyzing" while the
    # queue page showed nothing is exactly what the owner reported.
    assert got["retry"] == "retry_pending"
    assert got["never"] is None              # no job row → make no claim
    assert got["done"] is None               # analyzed rows are untouched


def test_running_job_also_reads_as_analyzing():
    rows = library.annotate_queue_state(
        [{"id": "r", "analyzed": False}], {"r": ("running", 1)})
    assert rows[0]["queue_state"] == "analyzing"


def test_job_states_reports_status_and_attempts(cache):
    cache.remember_meta([{"spotify_track_id": "j1", "track_name": "J", "artist_names": "A"}])
    cache.enqueue(["j1"])
    assert cache.job_states()["j1"][0] == "queued"
    # the real lifecycle: a dashboard visit re-queues a failure under the cap,
    # so it takes MAX_ATTEMPTS rounds to actually dead-letter
    for _ in range(3):
        cache.enqueue(["j1"])
        cache.claim_next()
        cache.fail("j1", "no usable source — title mismatch")
    status, attempts = cache.job_states()["j1"]
    assert status == "failed" and attempts >= 3          # dead-lettered
    rows = library.annotate_queue_state([{"id": "j1", "analyzed": False}],
                                        cache.job_states())
    assert rows[0]["queue_state"] == "no_source"


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


def test_consolidate_rows_collapses_and_carries_alt_names():
    from .library import annotate_dupes, consolidate_rows, library_view
    rows = annotate_dupes([
        {"id": "c", "name": "Song", "artist": "A", "duplicate_of": None,
         "analyzed": True, "tempo": 120.0},
        {"id": "t", "name": "Song - 2011 Remaster", "artist": "A",
         "duplicate_of": "c", "analyzed": True, "tempo": 120.0},
        {"id": "x", "name": "Other", "artist": "B", "duplicate_of": None,
         "analyzed": True, "tempo": 100.0},
        {"id": "orphan", "name": "Lost", "artist": "C",
         "duplicate_of": "missing", "analyzed": False, "tempo": None},
    ])
    out = consolidate_rows(rows)
    ids = [r["id"] for r in out]
    assert "t" not in ids                                   # twin collapsed
    assert "orphan" in ids                                  # fail-open: canon absent
    canon = next(r for r in out if r["id"] == "c")
    assert canon["n_versions"] == 2
    assert canon["alt_names"] == ["Song - 2011 Remaster"]
    # searching the TWIN's distinct title surfaces the canonical (red-team #5)
    v = library_view(out, q="remaster")
    assert [r["id"] for r in v["rows"]] == ["c"]
    # expand keeps every row (the transparency view)
    assert len(consolidate_rows(rows, expand=True)) == 4


def test_library_route_collapses_by_default_and_expands(rclient, monkeypatch, tmp_path):
    def _cache():
        tc = _seed_route_cache(tmp_path)
        tc.remember_meta([{"spotify_track_id": "cccccccc", "track_name": "Zephyr - Live",
                           "artist_names": "Beck"}])
        with tc._Session() as s:
            from ..store.models import TrackMeta
            s.get(TrackMeta, "cccccccc").duplicate_of = "aaaaaaaa"
            s.commit()
        return tc
    monkeypatch.setattr("src.webapp.app._feature_cache", _cache)
    r = rclient.get("/library")
    assert "releases of this recording" in r.text           # the chip on the canonical
    assert "↔ same recording as" not in r.text              # no twin ROW by default
    r2 = rclient.get("/library?dupes=all")
    assert "↔ same recording as" in r2.text                 # expanded: twin row + note
    # twin-title search surfaces the RECORDING (via alt_names), not nothing
    r3 = rclient.get("/library?q=live")
    assert "Zephyr" in r3.text and "releases of this recording" in r3.text


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


# ── pagination (P3): the growth gate, and the ways it could lie ──────────────
def _many(n: int) -> list[dict]:
    """A corpus big enough to page, with a sortable tempo that is NOT in id
    order — so a page-local sort would produce a different answer than a
    corpus-wide one."""
    return [{"id": f"t{i:04d}", "name": f"Song {i:04d}", "artist": "A",
             "popularity": i % 100, "duplicate_of": None, "analyzed": i % 3 != 0,
             "tempo": float((i * 37) % 200), "energy": 0.2, "brightness": 1000.0,
             "art": None} for i in range(n)]


def test_pages_concatenate_to_the_global_order():
    """THE sort-that-lies guard. Walking every page in sequence must reproduce
    the whole sorted set exactly — same rows, same order, none dropped, none
    repeated. A sort applied to the page instead of the corpus fails here."""
    full = library.library_view(_many(237), sort="tempo", order="desc")
    walked: list[str] = []
    pages = library.page_slice(full, per=50)["pages"]
    for p in range(1, pages + 1):
        walked += [r["id"] for r in library.page_slice(full, page=p, per=50)["page_rows"]]
    assert walked == [r["id"] for r in full["rows"]]
    assert len(walked) == 237


def test_search_reaches_a_row_that_would_live_on_the_last_page():
    """A lazy loader hides tracks from search. Pagination must not: the filter
    runs over the whole corpus, so a match on the far end comes back on page 1."""
    v = library.page_slice(library.library_view(_many(500), q="Song 0499"), per=50)
    assert [r["id"] for r in v["page_rows"]] == ["t0499"]
    assert v["pages"] == 1 and v["shown"] == 1


def test_caption_indices_describe_the_actual_slice():
    """from_index/to_index must be derived from the slice, never recomputed as
    page*per — that is how a last page claims rows it doesn't have."""
    full = library.library_view(_many(237))
    for per in library.PAGE_SIZES:
        nav = library.page_slice(full, per=per)
        for p in range(1, nav["pages"] + 1):
            page = library.page_slice(full, page=p, per=per)
            assert page["to_index"] - page["from_index"] + 1 == len(page["page_rows"])
        last = library.page_slice(full, page=nav["pages"], per=per)
        assert last["to_index"] == 237


def test_the_full_matching_set_survives_the_slice():
    """`rows` is what the my-songs count and the why-N explainer read. If a slice
    ever replaced it, those would describe one page and under-report the
    visitor's own library."""
    full = library.library_view(_many(237))
    page = library.page_slice(full, page=2, per=50)
    assert len(page["rows"]) == 237 and len(page["page_rows"]) == 50


def test_bad_page_and_per_params_never_break_the_page():
    full = library.library_view(_many(237))
    for bad in ("0", "-3", "abc", "", "99999", None):
        nav = library.page_slice(full, page=bad, per=100)
        assert 1 <= nav["page"] <= nav["pages"] and nav["page_rows"]
    for bad_per in ("100000", "abc", "", None, "7"):
        nav = library.page_slice(full, page=1, per=bad_per)
        assert len(nav["page_rows"]) == library.PAGE_SIZE   # allowlist, not int()


def test_show_all_is_one_page_of_everything():
    full = library.library_view(_many(237))
    nav = library.page_slice(full, per="all")
    assert nav["is_all"] and nav["pages"] == 1
    assert len(nav["page_rows"]) == 237 and nav["to_index"] == 237


def test_pager_always_reaches_the_first_and_last_page():
    """A pager that cannot reach the tail hides tracks as effectively as an
    infinite scroll does."""
    full = library.library_view(_many(2000))
    nav = library.page_slice(full, page=10, per=50)
    links = library.page_links({}, nav)
    labels = [x["label"] for x in links]
    assert labels[0] == "1" and labels[-1] == str(nav["pages"])
    assert "…" in labels                                   # gaps collapse
    assert sum(1 for x in links if x["current"]) == 1


def test_pager_urls_carry_the_view_but_never_junk():
    """URLs are rebuilt from an allowlist, so a crafted query can't plant junk
    in our own links — and the active filters DO survive paging."""
    full = library.library_view(_many(300))
    nav = library.page_slice(full, per=50)
    url = library.page_links({"q": "abc", "sort": "tempo", "filter": "needs-source",
                              "evil": "<script>"}, nav)[1]["url"]
    assert "q=abc" in url and "sort=tempo" in url and "filter=needs-source" in url
    assert "evil" not in url and "script" not in url


def test_empty_result_reports_zero_not_a_phantom_row():
    v = library.page_slice(library.library_view(_many(50), q="nothing matches"), per=50)
    assert v["page_rows"] == [] and v["from_index"] == 0 and v["to_index"] == 0


# ── "analyzing…" must mean the queue can show it (owner report 2026-07-25) ───
def test_a_failed_job_under_the_cap_is_not_called_analyzing():
    """142 tracks said "analyzing…" while /queue was empty. A failure under the
    cap was labelled "analyzing" on the theory a later dashboard visit would
    re-queue it — but a playlist-imported track is never revisited, so the retry
    never came and the label advertised work nothing was doing."""
    rows = [{"id": "a", "analyzed": False}, {"id": "b", "analyzed": False},
            {"id": "c", "analyzed": False}, {"id": "d", "analyzed": False}]
    states = {"a": ("queued", 0), "b": ("running", 1),
              "c": ("failed", 1), "d": ("failed", 3)}
    out = {r["id"]: r["queue_state"]
           for r in library.annotate_queue_state(rows, states, max_attempts=3)}
    assert out["a"] == "analyzing" and out["b"] == "analyzing"
    assert out["c"] == "retry_pending", "a failed job is not being analyzed"
    assert out["d"] == "no_source"


def test_only_queue_visible_work_may_claim_to_be_analyzing():
    """THE invariant behind the report: every row that says "analyzing…" links
    to /queue, so it must be a job the queue page would actually list —
    queued or running, nothing else."""
    states = {f"t{i}": s for i, s in enumerate([
        ("queued", 0), ("running", 0), ("failed", 1), ("failed", 3),
        ("done", 1), (None, 0)])}
    rows = [{"id": f"t{i}", "analyzed": False} for i in range(6)]
    annotated = library.annotate_queue_state(rows, states, max_attempts=3)
    claiming = {r["id"] for r in annotated if r["queue_state"] == "analyzing"}
    on_queue_page = {t for t, (s, _) in states.items() if s in ("queued", "running")}
    assert claiming == on_queue_page
