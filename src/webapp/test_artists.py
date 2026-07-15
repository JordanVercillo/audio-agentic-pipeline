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


def test_artists_anon_redirects(client):
    r = client.get("/artists", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


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
    # the borrowed-time endpoint going dark → honest caption, page still renders
    monkeypatch.setattr("src.webapp.app.fetch_artist_top_tracks",
                        lambda aid, sp: pd.DataFrame())
    r2 = client.get("/artist/ar1AAAAAA")
    assert r2.status_code == 200 and "retired" in r2.text
    assert "Your top tracks by Muse" in r2.text           # the core never depends on it


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
