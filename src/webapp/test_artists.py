"""
test_artists.py — the Artists surface (Epic P / P3.2), synthetic.

Pure view-logic tests + route matrix (anon/guest/authed) with mocked fetchers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from . import config
from .artists import (
    artist_rollup,
    comparison_svg,
    filter_by_genre,
    genre_strip,
    genre_tokens,
    nearest_artists,
    primary_artist,
    your_top_by_artist,
)

# ── fixtures: a tiny two-artist library ──────────────────────────────────────
_METAS = {
    "m1": {"track_name": "Hysteria", "artist_names": "Muse"},
    "m2": {"track_name": "Uprising", "artist_names": "Muse, Someone"},
    "q1": {"track_name": "Breathe", "artist_names": "Quiet Band"},
    "q2": {"track_name": "Hush", "artist_names": "Quiet Band"},
    "x1": {"track_name": "Solo", "artist_names": "Unanalyzed Act"},
}
_PERC = {
    "m1": {"tempo": 140.0, "energy": 0.9, "danceability": 0.8},
    "m2": {"tempo": 150.0, "energy": 0.8, "danceability": 0.6},
    "q1": {"tempo": 80.0, "energy": 0.2, "danceability": 0.3},
    "q2": {"tempo": 90.0, "energy": 0.3, "danceability": 0.4},
}
_AMETA = {
    "ar1": {"artist_id": "ar1", "artist_name": "Muse", "genres": "Rock, Prog",
            "followers": 1000, "popularity": 78, "image_url": "http://img/m"},
    "ar2": {"artist_id": "ar2", "artist_name": "Quiet Band", "genres": "",
            "followers": 10, "popularity": 12, "image_url": None},
}
_TASTE_ARTISTS = [{"name": "Muse", "genres": "rock"},
                  {"name": "Quiet Band", "genres": ""},
                  {"name": "Ghost Act", "genres": ""}]   # not in artist_meta


def test_primary_artist_matches_clusters_rule():
    assert primary_artist("Muse, Someone Else") == "Muse"
    assert primary_artist("  Solo ") == "Solo"
    assert primary_artist(None) == "" and primary_artist("") == ""


def test_artist_rollup_cards():
    cards = artist_rollup(_TASTE_ARTISTS, _METAS, _PERC, _AMETA)
    assert [c["name"] for c in cards] == ["Muse", "Quiet Band", "Ghost Act"]  # rank order kept
    muse = cards[0]
    assert muse["artist_id"] == "ar1" and muse["popularity"] == 78
    assert muse["genres"] == "Rock, Prog"          # stored copy beats the taste dict
    assert muse["n_tracks"] == 2 and muse["n_analyzed"] == 2
    assert muse["feat"]["tempo"] == pytest.approx(145.0)   # mean over analyzed
    ghost = cards[2]
    assert ghost["artist_id"] is None              # unknown → unlinked card
    assert ghost["n_tracks"] == 0 and ghost["feat"]["tempo"] is None


def test_genre_tokens_filter_and_strip():
    assert genre_tokens("Rock, Prog") == ["rock", "prog"]
    cards = artist_rollup(_TASTE_ARTISTS, _METAS, _PERC, _AMETA)
    assert [c["name"] for c in filter_by_genre(cards, "rock")] == ["Muse"]
    assert filter_by_genre(cards, "") == cards      # empty filter = no-op
    strip = genre_strip(cards)
    assert strip["covered"] == 1 and strip["total"] == 3   # honesty numbers
    assert strip["genres"][0] == {"genre": "prog", "count": 1} or \
           {"genre": "rock", "count": 1} in strip["genres"]


def test_comparison_svg_ranked_and_escaped():
    cards = artist_rollup(
        [{"name": "Muse"}, {"name": "Quiet Band"}, {"name": "<Evil>"}],
        {**_METAS, "e1": {"track_name": "X", "artist_names": "<Evil>"}},
        {**_PERC, "e1": {"tempo": 100.0, "energy": 0.5, "danceability": 0.5}},
        _AMETA)
    svg = comparison_svg(cards, "energy", "Energy")
    assert svg.startswith("<svg")
    assert svg.index(">Muse<") < svg.index(">Quiet Band<")   # ranked desc by energy
    assert "&lt;Evil&gt;" in svg and "<Evil>" not in svg     # names escaped
    assert 'class="cmp-val"' in svg                          # value labels present
    assert comparison_svg(cards[:1], "energy", "Energy") == ""  # <2 rows → ""


def test_your_top_by_artist_derived_core():
    ranges = {"short_term": ["q1", "m2"], "medium_term": ["m1", "q2"],
              "long_term": ["m2", "x1"]}
    got = your_top_by_artist("Muse", ranges, _METAS, limit=5)
    assert [t["id"] for t in got] == ["m2", "m1"]   # first-appearance order, deduped
    assert got[0]["window"] == "short_term"
    assert your_top_by_artist("Nobody", ranges, _METAS) == []


def test_nearest_artists_sounds_alike_here():
    # 3 artists × 2 tracks with clearly separated feature spaces
    metas = {f"{a}{i}": {"track_name": f"{a}{i}", "artist_names": name}
             for a, name in (("l", "Loud A"), ("k", "Loud B"), ("s", "Soft C"))
             for i in (1, 2)}
    feats = {}
    base = {"l": 0.9, "k": 0.85, "s": 0.1}
    for a, v in base.items():
        for i in (1, 2):
            feats[f"{a}{i}"] = {"tempo_bpm": 100 + 100 * v, "rms_mean": v,
                                "zcr_mean": v / 2, "spectral_centroid_mean": 3000 * v}
    got = nearest_artists("Loud A", feats, metas, k=2)
    assert [g["name"] for g in got] == ["Loud B", "Soft C"]   # acoustically nearest first
    assert got[0]["distance"] < got[1]["distance"]
    assert nearest_artists("Missing", feats, metas) == []


# ── route matrix (anon / guest / authed) ─────────────────────────────────────
@pytest.fixture
def client():
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


def _seed_cache(tmp_path):
    """A tiny library: 2 artists with analyzed tracks + artist_meta rows."""
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'artists.db'}")
    tc.remember_meta([
        {"spotify_track_id": "m1", "track_name": "Hysteria", "artist_names": "Muse"},
        {"spotify_track_id": "m2", "track_name": "Uprising", "artist_names": "Muse"},
        {"spotify_track_id": "q1", "track_name": "Breathe", "artist_names": "Quiet Band"},
    ])
    for tid, tempo, e in (("m1", 140.0, 0.9), ("m2", 150.0, 0.8), ("q1", 80.0, 0.2)):
        tc.upsert(tid, {"tempo_bpm": tempo, "rms_mean": e,
                        "spectral_centroid_mean": 3000 * e, "zcr_mean": e / 5})
        tc.upsert_perceptual(tid, {"tempo": tempo, "energy": e, "danceability": e},
                             version="perceptual-v1")
    tc.remember_artists([
        {"artist_id": "ar1AAAAAA", "artist_name": "Muse", "genres": "rock, prog",
         "followers": 1000, "popularity": 78},
        {"artist_id": "ar2BBBBBB", "artist_name": "Quiet Band", "genres": "ambient"},
    ])
    return tc


_TASTE = {"range_ids": {"short_term": ["m1", "q1"], "long_term": ["m2"]},
          "artists": [{"name": "Muse", "genres": ""},
                      {"name": "Quiet Band", "genres": ""}]}


def test_artists_is_public_and_shows_the_corpus_not_a_taste(client, monkeypatch, tmp_path):
    """R1: was viewer-gated and built from session["taste"]["artists"], so it
    showed ~15 artists and anon saw none. It is now the CORPUS index, which is
    what makes it publishable — it carries nothing personal."""
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    r = client.get("/artists", follow_redirects=False)
    assert r.status_code == 200
    assert "Your artists" not in r.text or 'tab=mine' not in r.text  # no personal tab for anon


def test_artists_mine_tab_falls_back_to_all_for_anon(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    r = client.get("/artists?tab=mine", follow_redirects=False)
    assert r.status_code == 200


def test_artists_guest_renders_readonly(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE, guest=True))
    r = client.get("/artists")
    assert r.status_code == 200
    assert "Muse" in r.text and "rock" in r.text          # card + genre chip (stored copy)
    assert 'class="artist-cmp"' in r.text                 # the comparison chart
    assert "Genres known for" in r.text and "2 of 2</b>" in r.text  # coverage honesty
    assert "Demo view" in r.text and "Analyze these" not in r.text  # read-only


def test_artists_genre_filter(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    r = client.get("/artists?genre=ambient")
    assert "Quiet Band" in r.text and "Hysteria" not in r.text
    assert ">Muse<" not in r.text                         # filtered out


def test_artist_page_guest_derived_core_no_live(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE, guest=True))
    r = client.get("/artist/ar1AAAAAA")
    assert r.status_code == 200
    assert "Your top tracks by Muse" in r.text
    assert "Hysteria" in r.text                           # derived core renders
    assert "read-only" in r.text                          # guest live-caption
    assert "Analyze these" not in r.text


def test_artist_page_authed_live_rows_and_analyze(client, monkeypatch, tmp_path):
    tc = _seed_cache(tmp_path)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    live = pd.DataFrame([
        {"spotify_track_id": "m1", "track_name": "Hysteria", "artist_names": "Muse",
         "popularity": 80, "duration_ms": 200000},                    # already analyzed
        {"spotify_track_id": "new9", "track_name": "New Cut", "artist_names": "Muse",
         "popularity": 70, "duration_ms": 180000},                     # not analyzed
    ])
    monkeypatch.setattr("src.webapp.app.fetch_artist_top_tracks", lambda aid, sp: live)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    r = client.get("/artist/ar1AAAAAA")
    assert r.status_code == 200
    assert "official top 10" in r.text and "New Cut" in r.text
    assert "Analyze these" in r.text                      # un-analyzed row → button
    assert tc.get_meta("new9")["track_name"] == "New Cut"  # live rows persisted to meta
    # the borrowed-time endpoint going dark → honest caption, page still renders.
    # (Bust the 10-min top-10 memo first — session 36: non-empty results cache.)
    client.app.state.artist_top_cache.clear()
    monkeypatch.setattr("src.webapp.app.fetch_artist_top_tracks",
                        lambda aid, sp: pd.DataFrame())
    r2 = client.get("/artist/ar1AAAAAA")
    assert r2.status_code == 200 and "retired" in r2.text
    assert "Your top tracks by Muse" in r2.text           # the core never depends on it


def test_artist_top10_memoized_within_ttl(client, monkeypatch, tmp_path):
    # session-36 hang fix: repeat page views must NOT re-hit the borrowed-time
    # endpoint (heavy browsing was rate-limiting it into stuck renders).
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    calls = {"n": 0}

    def fetcher(aid, sp):
        calls["n"] += 1
        return pd.DataFrame([{"spotify_track_id": "m1", "track_name": "Hysteria",
                              "artist_names": "Muse", "popularity": 80}])
    monkeypatch.setattr("src.webapp.app.fetch_artist_top_tracks", fetcher)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    client.get("/artist/ar1AAAAAA")
    client.get("/artist/ar1AAAAAA")
    assert calls["n"] == 1  # second view served from the 10-min memo


def test_artist_page_unknown_or_bad_id_redirects(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: _seed_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    r = client.get("/artist/zzUNKNOWNzz", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/artists"
    r2 = client.get("/artist/bad!id", follow_redirects=False)   # charset guard
    assert r2.status_code == 303 and r2.headers["location"] == "/artists"


def test_artist_analyze_gates_and_enqueues(client, monkeypatch, tmp_path):
    tc = _seed_cache(tmp_path)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    live = pd.DataFrame([{"spotify_track_id": "new9", "track_name": "New Cut",
                          "artist_names": "Muse", "duration_ms": 180000}])
    monkeypatch.setattr("src.webapp.app.fetch_artist_top_tracks", lambda aid, sp: live)
    # anon and guest never enqueue
    r = client.post("/artist/ar1AAAAAA/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE, guest=True))
    r = client.post("/artist/ar1AAAAAA/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert tc.job_status(["new9"])["queued"] == 0
    # authed → server-side re-fetch, remembered + queued (≤10), back to the page
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    r = client.post("/artist/ar1AAAAAA/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/artist/ar1AAAAAA"
    assert tc.job_status(["new9"])["queued"] == 1


def test_fetch_artist_top_tracks_absent_safe():
    from src.ingestion.fetchers import fetch_artist_top_tracks

    class _Dark:  # the borrowed-time endpoint going dark
        def artist_top_tracks(self, aid, country=None):
            import spotipy
            raise spotipy.exceptions.SpotifyException(403, -1, "removed")

    assert fetch_artist_top_tracks("ar1", sp=_Dark()).empty   # absent-safe, never raises

    class _Alive:
        def artist_top_tracks(self, aid, country=None):
            return {"tracks": [{"id": f"t{i}", "name": f"Song {i}", "explicit": False,
                                "duration_ms": 1000, "disc_number": 1, "track_number": i,
                                "artists": [{"id": "ar1", "name": "Muse"}],
                                "album": {}, "popularity": 60 + i}
                               for i in range(12)]}          # API would cap at 10 anyway

    df = fetch_artist_top_tracks("ar1", sp=_Alive())
    assert len(df) == 10                                      # hard-capped at 10
    assert list(df["rank"]) == list(range(1, 11))
    assert df.iloc[0]["primary_artist_id"] == "ar1"


# ── R1 (P4.7.2): the corpus-scale index ──────────────────────────────────────
def test_corpus_index_groups_by_id_and_counts_the_name_fallback():
    """Grouping on primary_artist_id is not a second identity system — it's
    Spotify's own id, already stored and already the /artist/{id} route key.
    Tracks without one fall back to the NAME and are COUNTED, because two
    different artists sharing a name would otherwise merge invisibly."""
    from .artists import corpus_artist_index

    metas = {
        "t1": {"artist_names": "Muse", "track_name": "A"},
        "t2": {"artist_names": "Muse", "track_name": "B"},
        "t3": {"artist_names": "Nameless", "track_name": "C"},   # no id anywhere
    }
    lib = [{"id": "t1", "primary_artist_id": "MUSEID"},
           {"id": "t2", "primary_artist_id": "MUSEID"},
           {"id": "t3"}]
    idx = corpus_artist_index(metas, {}, {"MUSEID": {"artist_id": "MUSEID"}}, lib)

    assert idx["n_artists"] == 2
    muse = [c for c in idx["cards"] if c["name"] == "Muse"][0]
    assert muse["artist_id"] == "MUSEID" and muse["n_tracks"] == 2
    assert muse["keyed_by"] == "id"
    nameless = [c for c in idx["cards"] if c["name"] == "Nameless"][0]
    assert nameless["artist_id"] is None and nameless["keyed_by"] == "name"
    # the fallback is REPORTED, never silent
    assert idx["n_name_keyed"] == 1 and idx["n_tracks_name_matched"] == 1
    assert idx["n_linkable"] == 1


def test_corpus_index_is_not_bounded_by_a_taste_snapshot():
    """The bug R1 fixes: the page could only show artists in session taste."""
    from .artists import corpus_artist_index

    metas = {f"t{i}": {"artist_names": f"Artist {i}"} for i in range(40)}
    lib = [{"id": f"t{i}", "primary_artist_id": f"A{i}"} for i in range(40)]
    idx = corpus_artist_index(metas, {}, {}, lib)
    assert idx["n_artists"] == 40


def test_artists_search_and_pagination_cover_the_whole_index():
    from .artists import artists_view, corpus_artist_index
    from .library import page_slice

    metas = {f"t{i}": {"artist_names": f"Band {i:03d}"} for i in range(120)}
    lib = [{"id": f"t{i}", "primary_artist_id": f"A{i}"} for i in range(120)]
    idx = corpus_artist_index(metas, {}, {}, lib)

    v = artists_view(idx, q="Band 0")           # Band 000-099 -> 100 matches
    assert v["shown"] == 100 and v["total"] == 120
    # per is an ALLOWLIST (50/100/250) — an arbitrary size falls back, which is
    # the ?per=100000 guard, so pagination is exercised with a real size.
    page = page_slice(v, page=2, per=50)
    assert page["pages"] == 2 and len(page["page_rows"]) == 50
    assert page["from_index"] == 51 and page["to_index"] == 100
    # the lede counts the whole matching set, never the visible slice
    assert v["shown"] == 100


def test_song_page_links_to_its_artist(client, monkeypatch, tmp_path):
    """F5: there was no path from a song to its artist anywhere in the app."""
    cache = _seed_cache(tmp_path)
    cache.remember_meta([{"spotify_track_id": "s1", "track_name": "Song",
                          "artist_names": "Muse", "primary_artist_id": "MUSEID"}])
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: cache)
    r = client.get("/song/s1")
    assert r.status_code == 200
    assert '/artist/MUSEID' in r.text


def test_a_name_only_group_folds_into_its_id_group():
    """Found by searching the LIVE index: "Muse" rendered as TWO cards because
    some of its tracks carry no primary_artist_id. Avoiding a silent merge is
    right; showing the same artist twice is not."""
    from .artists import corpus_artist_index

    metas = {"t1": {"artist_names": "Muse"}, "t2": {"artist_names": "Muse"},
             "t3": {"artist_names": "Muse"}}
    lib = [{"id": "t1", "primary_artist_id": "MUSEID"},
           {"id": "t2", "primary_artist_id": "MUSEID"},
           {"id": "t3"}]                                  # no id on this one
    idx = corpus_artist_index(metas, {}, {"MUSEID": {"artist_id": "MUSEID"}}, lib)

    assert idx["n_artists"] == 1
    card = idx["cards"][0]
    assert card["artist_id"] == "MUSEID" and card["n_tracks"] == 3
    # folded, but COUNTED — the page can say how much rests on a name match
    assert card["n_name_matched"] == 1
    assert idx["n_tracks_folded_by_name"] == 1


def test_an_ambiguous_name_is_left_split_on_purpose():
    """Two DIFFERENT artists sharing a name is exactly the case a silent merge
    would fuse — so that one stays split even though it looks untidy."""
    from .artists import corpus_artist_index

    metas = {"t1": {"artist_names": "Nova"}, "t2": {"artist_names": "Nova"},
             "t3": {"artist_names": "Nova"}}
    lib = [{"id": "t1", "primary_artist_id": "NOVA_A"},
           {"id": "t2", "primary_artist_id": "NOVA_B"},   # same name, other id
           {"id": "t3"}]                                  # ambiguous → no fold
    idx = corpus_artist_index(metas, {}, {}, lib)

    assert idx["n_artists"] == 3, "an ambiguous name was silently merged"
    assert idx["n_tracks_folded_by_name"] == 0
    assert idx["n_name_keyed"] == 1


# ── R2/R4a (P4.7.3): discography + chronological drift ───────────────────────
def _ident(rows):
    return {t: {"album_name": n, "album_type": k, "album_release_date": d}
            for t, n, k, d in rows}


def test_albums_group_by_name_and_type_and_take_the_earliest_date():
    """Live data has "Absolution" under 2003 AND 2004 (regional releases) and
    "Will Of The People" as both an album and a single. Collapsing on name
    alone fuses a record with its lead single; keeping every release id shows
    one record twice."""
    from .artists import artist_albums

    ident = _ident([
        ("t1", "Absolution", "album", "2003-09-15"),
        ("t2", "Absolution", "album", "2004-03-23"),   # reissue
        ("t3", "Will Of The People", "album", "2022-08-26"),
        ("t4", "Will Of The People", "single", "2022-06-17"),
    ])
    albums = artist_albums(["t1", "t2", "t3", "t4"], ident, {})
    names = [(a["name"], a["type"], a["year"], a["n_tracks"]) for a in albums]
    assert ("Absolution", "album", "2003", 2) in names       # merged, earliest date
    assert ("Will Of The People", "album", "2022", 1) in names
    assert ("Will Of The People", "single", "2022", 1) in names
    assert len(albums) == 3


def test_albums_are_chronological_and_undated_sort_last():
    from .artists import artist_albums

    ident = _ident([("t1", "Later", "album", "2015-01-01"),
                    ("t2", "Earlier", "album", "2001-01-01"),
                    ("t3", "Undated", "album", "")])
    albums = artist_albums(["t1", "t2", "t3"], ident, {})
    assert [a["name"] for a in albums] == ["Earlier", "Later", "Undated"]


def test_drift_refuses_to_draw_a_trend_from_too_few_points():
    """Two points is a line through anything (journal #28)."""
    from .artists import artist_drift

    two = [{"year": "2001", "name": "A", "n_analyzed": 1, "feat": {"energy": 0.2}},
           {"year": "2010", "name": "B", "n_analyzed": 1, "feat": {"energy": 0.8}}]
    assert artist_drift(two, "energy") is None
    three = two + [{"year": "2020", "name": "C", "n_analyzed": 1,
                    "feat": {"energy": 0.5}}]
    d = artist_drift(three, "energy")
    assert d is not None and d["n"] == 3
    assert d["from_year"] == "2001" and d["to_year"] == "2020"
    assert d["direction"] == "up" and round(d["delta"], 2) == 0.30


def test_drift_ignores_releases_with_no_analyzed_tracks():
    from .artists import artist_drift

    albums = [{"year": "2001", "name": "A", "n_analyzed": 0, "feat": {"energy": None}},
              {"year": "2005", "name": "B", "n_analyzed": 2, "feat": {"energy": 0.3}},
              {"year": "2010", "name": "C", "n_analyzed": 2, "feat": {"energy": 0.4}},
              {"year": "2015", "name": "D", "n_analyzed": 2, "feat": {"energy": 0.6}}]
    d = artist_drift(albums, "energy")
    assert d["n"] == 3 and d["from_year"] == "2005"


def test_artist_signature_reuses_the_shared_vocabulary_and_adds_spread():
    """R3: the words and the ±2σ cap come from analytics/scales, not a copy.
    Spread is the part a centroid distance structurally cannot say — it
    collapses a whole catalogue to one point, so a range artist and a formula
    artist look identical to it."""
    from .analytics import _SIGNATURE_DIMS
    from .artists import artist_signature

    cols = [c for c, *_ in _SIGNATURE_DIMS]
    # population: 60 tracks with moderate spread on every dim
    pop = [{c: 1.0 + (i % 10) * 0.1 for c in cols} for i in range(60)]
    # a WIDE artist: swings far on every dim
    wide_ids = [f"w{i}" for i in range(8)]
    wide = {f"w{i}": {c: 1.0 + (i % 8) * 0.5 for c in cols} for i in range(8)}
    got = artist_signature(wide_ids, wide, pop)
    assert got is not None
    assert got["n_tracks"] == 8
    assert {d["feature"] for d in got["signature"]} <= {lbl for _c, lbl, *_ in _SIGNATURE_DIMS}
    assert got["widest"]["sigma"] >= got["narrowest"]["sigma"]
    assert got["range_artist"] is True


def test_artist_signature_refuses_on_too_few_tracks():
    from .analytics import _SIGNATURE_DIMS
    from .artists import artist_signature

    cols = [c for c, *_ in _SIGNATURE_DIMS]
    pop = [{c: float(i) for c in cols} for i in range(30)]
    two = {"a": {c: 1.0 for c in cols}, "b": {c: 2.0 for c in cols}}
    assert artist_signature(["a", "b"], two, pop) is None


def test_a_card_only_links_when_the_artist_page_can_actually_resolve_it():
    """The director review's blocker: `n_linkable` was computed from the TRACK's
    primary_artist_id while /artist/{id} resolves through artist_meta — so 826
    of 891 links on the new PUBLIC page bounced, under a caption asserting they
    worked. Two components, two rules, one claim (journal #27)."""
    from .artists import corpus_artist_index

    metas = {"t1": {"artist_names": "Known"}, "t2": {"artist_names": "Unknown"}}
    lib = [{"id": "t1", "primary_artist_id": "KNOWN"},
           {"id": "t2", "primary_artist_id": "MISSING"}]   # no artist_meta row
    artist_meta = {"KNOWN": {"artist_id": "KNOWN", "artist_name": "Known"}}
    idx = corpus_artist_index(metas, {}, artist_meta, lib)

    known = [c for c in idx["cards"] if c["name"] == "Known"][0]
    unknown = [c for c in idx["cards"] if c["name"] == "Unknown"][0]
    assert known["artist_id"] == "KNOWN"
    assert unknown["artist_id"] is None, "a card linked to a page that 303s"
    assert idx["n_linkable"] == 1, "the count must equal the links that resolve"


def test_every_link_the_artists_page_renders_resolves(client, monkeypatch, tmp_path):
    """The regression class a unit test cannot see: unit tests pass
    artist_meta={} and so never exercise the link/route disagreement."""
    cache = _seed_cache(tmp_path)
    cache.remember_meta([{"spotify_track_id": "x1", "track_name": "S",
                          "artist_names": "Linked", "primary_artist_id": "AID1aaaaaaaaaaaaaaaaaa"}])
    cache.remember_artists([{"artist_id": "AID1aaaaaaaaaaaaaaaaaa", "artist_name": "Linked",
                             "genres": "rock"}])
    cache.remember_meta([{"spotify_track_id": "x2", "track_name": "S2",
                          "artist_names": "Orphan", "primary_artist_id": "AID9zzzzzzzzzzzzzzzzzz"}])
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: cache)

    r = client.get("/artists")
    assert r.status_code == 200
    import re
    for aid in set(re.findall(r'href="/artist/([0-9A-Za-z]+)"', r.text)):
        resp = client.get(f"/artist/{aid}", follow_redirects=False)
        assert resp.status_code == 200, f"/artists linked to {aid}, which 303s"


# ── drift: the two ways it used to overclaim ────────────────────────────────
def test_drift_names_an_arc_instead_of_flattening_it_to_up():
    """It reported `last - first` while REQUIRING three points — so the two
    middle releases the rule insisted on were then ignored, and the most common
    catalogue arc (got loud, came back down) rendered as 'up'.
    Director review 2026-07-31."""
    from .artists import artist_drift

    albums = [{"year": y, "name": n, "n_analyzed": 2, "feat": {"rms_mean": v}}
              for y, n, v in (("2001", "A", 0.20), ("2005", "B", 0.55),
                              ("2009", "C", 0.80), ("2013", "D", 0.50),
                              ("2017", "E", 0.25))]
    d = artist_drift(albums, "rms_mean")
    assert d["n"] == 5
    assert d["shape"] == "arc", "an up-then-down catalogue was flattened"
    assert d["max"] == 0.80, "the peak the arc is about is not reported"
    # and the endpoints alone would have said "up" for four of five releases
    assert round(d["delta"], 2) == 0.05


def test_drift_reads_the_trend_not_the_endpoints():
    """A catalogue that rises steadily but dips on the last release is still
    rising; `last - first` says it fell."""
    from .artists import artist_drift

    albums = [{"year": y, "name": n, "n_analyzed": 2, "feat": {"rms_mean": v}}
              for y, n, v in (("2000", "A", 0.10), ("2004", "B", 0.30),
                              ("2008", "C", 0.50), ("2012", "D", 0.70),
                              ("2016", "E", 0.09))]
    d = artist_drift(albums, "rms_mean")
    assert d["delta"] < 0, "the endpoints do fall — that is the trap"
    assert d["slope_per_year"] > 0, "the trend across all five releases rises"


def test_drift_default_column_is_a_measurement_not_a_corpus_rank():
    """`energy` is a percentile RANK against the current corpus. With it as the
    default, another artist's tracks arriving moved THIS artist's 'drift'
    without a note of their music changing — the opposite of the artist fact
    the surface claims to state."""
    import inspect

    from . import app as app_mod
    from .artists import artist_drift

    assert inspect.signature(artist_drift).parameters["column"].default == "rms_mean"
    src = inspect.getsource(app_mod)
    assert 'artist_drift(albums, "energy")' not in src, (
        "/artist is back to drifting on a corpus-relative rank")


def test_drift_labels_itself_from_the_shared_registry():
    """The template renders `drift.label`; nothing may restate a column name
    (journal #27 / P4.7.0 — `rms_mean` was 'Loudness' on one page and 'Energy'
    on another for months)."""
    from . import scales
    from .artists import artist_drift

    albums = [{"year": y, "name": "A", "n_analyzed": 1, "feat": {"rms_mean": v}}
              for y, v in (("2001", 0.2), ("2005", 0.4), ("2009", 0.6))]
    d = artist_drift(albums, "rms_mean")
    assert d["label"] == scales.display_name("rms_mean")
    assert d["direction"] == "up" and d["shape"] == "trend"


# ── the pager must carry the filters the surface actually has ──────────────
def test_pager_carries_the_genre_filter_and_the_chart_column():
    """Paging dropped `genre` and `f` because neither was in the allowlist —
    page 2 of a genre view silently became page 2 of everything, with the
    comparison chart reset to its default column (director review 2026-07-31).
    """
    from urllib.parse import parse_qs

    from .library import pager_query

    params = {"genre": "indie rock", "f": "brightness", "q": "the",
              "per": "60", "page": "3"}
    got = parse_qs(pager_query(params, page=2))
    assert got.get("genre") == ["indie rock"], "the genre filter was dropped"
    assert got.get("f") == ["brightness"], "the chart column was reset"
    assert got.get("q") == ["the"] and got.get("per") == ["60"]
    # and an unset filter still contributes nothing to the URL
    assert "genre" not in parse_qs(pager_query({"q": "x"}, page=2))


def test_artists_heading_and_genre_caption_count_the_same_population(client):
    """Two captions counted something other than what they said: the heading
    rendered "N of " (nothing supplied `total_cards`), and the genre strip said
    "artists on this page" while counting every match."""
    r = client.get("/artists?per=15")
    assert r.status_code == 200
    body = r.text
    assert "of  artists" not in body, "total_cards is unsupplied again"
    assert "artists on this page" not in body, (
        "the genre caption claims a page but counts every match")


def test_artist_page_never_claims_a_track_credited_to_another_artist_id():
    """The index deliberately keeps an id-keyed artist and a name-keyed one
    apart — two acts share a name often enough that fusing them attributes
    someone else's catalogue to this page, and the drift and acoustic profile
    then describe a chimera. /artist/{id} was fusing exactly what /artists
    splits (director review 2026-07-31).

    Asserted at the selection rule, which is the thing that was wrong.
    """
    from .artists import primary_artist

    rows = [{"id": "a1", "primary_artist_id": "ART1", "artist": "Nirvana"},
            {"id": "a2", "primary_artist_id": None, "artist": "Nirvana"},
            {"id": "a3", "primary_artist_id": "ART2", "artist": "Nirvana"},
            {"id": "a4", "primary_artist_id": None, "artist": "Someone Else"}]

    def select(artist_id, name):
        by_id, by_name = [], []
        for r in rows:
            pid = r.get("primary_artist_id")
            if pid == artist_id:
                by_id.append(r["id"])
            elif not pid and primary_artist(r.get("artist") or "").lower() == name.lower():
                by_name.append(r["id"])
        return by_id, by_name

    by_id, by_name = select("ART1", "Nirvana")
    assert by_id == ["a1"]
    assert by_name == ["a2"], "the unresolved row is what name-matching is for"
    assert "a3" not in by_id + by_name, (
        "a track credited to a DIFFERENT artist id was claimed by name")

    # and the other act keeps its own track
    assert select("ART2", "Nirvana")[0] == ["a3"]
