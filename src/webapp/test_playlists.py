"""
test_playlists.py — the Playlists surface (Epic I / P3.4), synthetic.

Pure builder tests (own+collaborative filter, coverage copy) + the route matrix
(anon / guest / authed-no-scope / authed-scope) with mocked fetchers. No real
API (ground rule #5).
"""

from __future__ import annotations

import pandas as pd
import pytest

from . import config, playlists

_PL_DF = pd.DataFrame([
    {"playlist_id": "mine1", "playlist_name": "Road Trip", "owner_id": "me",
     "owner_name": "Me", "collaborative": False, "track_count": 40, "image_url": None},
    {"playlist_id": "collab1", "playlist_name": "Shared", "owner_id": "friend",
     "owner_name": "Friend", "collaborative": True, "track_count": 12, "image_url": None},
    {"playlist_id": "theirs1", "playlist_name": "Someone Else", "owner_id": "stranger",
     "owner_name": "Stranger", "collaborative": False, "track_count": 99, "image_url": None},
])


def test_cards_filter_to_own_and_collaborative():
    cards = playlists.playlist_cards(_PL_DF, me_id="me")
    assert {c["id"] for c in cards} == {"mine1", "collab1"}  # stranger's excluded


def test_cards_fail_closed_without_me_id():
    cards = playlists.playlist_cards(_PL_DF, me_id=None)
    assert {c["id"] for c in cards} == {"collab1"}  # only collaborative, never a stranger's


def test_importable_ids_matches_cards():
    assert playlists.importable_ids(_PL_DF, "me") == {"mine1", "collab1"}


def test_empty_df_is_safe():
    assert playlists.playlist_cards(None, "me") == []
    assert playlists.playlist_cards(pd.DataFrame(), "me") == []


def test_nan_cover_becomes_none_not_truthy():
    # journal #30 on the display path: image_url None → pandas nan (truthy) →
    # <img src="nan"> → the browser GETs /nan. Must map to None.
    df = pd.DataFrame([{"playlist_id": "p1", "playlist_name": "NoCover",
                        "owner_id": "me", "owner_name": "Me",
                        "collaborative": False, "track_count": 3,
                        "image_url": None}])
    card = playlists.playlist_cards(df, "me")[0]
    assert card["image"] is None


def test_coverage_line_reports_queued_skipped_and_remaining():
    line = playlists.coverage_line(queued=100, skipped=40, remaining=24, cap=100)
    assert "100" in line and "skipped <b>40</b>" in line and "24" in line and "cap" in line
    clean = playlists.coverage_line(queued=12, skipped=0, remaining=0, cap=100)
    assert "12" in clean and "skipped" not in clean and "cap" not in clean


# ── route matrix ─────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from .app import create_app
    return TestClient(create_app())


def _seed_session(*, guest=False, scope=None):
    from .app import _signer, _store
    sid = _store.new()
    sess = _store.get(sid)
    if guest:
        sess["is_guest"] = True
    else:
        tok = {"access_token": "x"}
        if scope is not None:
            tok["scope"] = scope
        sess["token"] = tok
    return _signer.sign(sid)


def test_playlists_anon_and_guest_redirect(client):
    r = client.get("/playlists", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    client.cookies.set(config.SESSION_COOKIE, _seed_session(guest=True))
    r2 = client.get("/playlists", follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/"


def test_playlists_authed_no_scope_shows_reconsent_and_never_fetches(client, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not fetch without the scope")
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", _boom)
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", _boom)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope="user-top-read"))
    r = client.get("/playlists")
    assert r.status_code == 200 and "Reconnect Spotify" in r.text


def test_playlists_authed_with_scope_lists_own_only(client, monkeypatch):
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", lambda c: {"user_id": "me"})
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", lambda c: _PL_DF)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.get("/playlists")
    assert r.status_code == 200
    assert "Road Trip" in r.text and "Shared" in r.text
    assert "Someone Else" not in r.text  # stranger's playlist filtered out


# ── Analyze POST (P3.4c) ─────────────────────────────────────────────────────
class _FakeCache:
    def __init__(self, cached=None, active=None):
        self.cached = cached or set()
        self.active = active or set()
        self.enqueued: list = []
        self.remembered: list = []

    def cached_ids(self, ids):
        return {i for i in ids if i in self.cached}

    def active_ids(self, ids):
        return {i for i in ids if i in self.active}

    def remember_meta(self, recs):
        self.remembered = recs

    def enqueue(self, ids):
        self.enqueued = ids
        return list(ids)


def _mock_membership(monkeypatch):
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", lambda c: {"user_id": "me"})
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", lambda c: _PL_DF)


def test_analyze_cap_spends_slots_on_new_tracks_only(client, monkeypatch):
    # owner report (session 36): analyzed/queued tracks must be SKIPPED first,
    # the cap applied to what's genuinely new — re-Analyze walks deeper each time.
    _mock_membership(monkeypatch)
    big = pd.DataFrame([{"spotify_track_id": f"t{i}", "track_name": f"S{i}",
                         "artist_names": "A"} for i in range(2000)])
    monkeypatch.setattr("src.webapp.app.fetch_playlist_tracks", lambda pid, c: big)
    fake = _FakeCache(cached={f"t{i}" for i in range(30)},      # first 30 analyzed
                      active={f"t{i}" for i in range(30, 50)})  # next 20 already queued
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/playlists"
    cap = config.PLAYLIST_IMPORT_CAP
    assert len(fake.enqueued) == cap                          # cap = a TOTAL of NEW tracks
    assert fake.enqueued == [f"t{i}" for i in range(50, 50 + cap)]  # skip → then cap


def test_analyze_excludes_local_and_none_ids(client, monkeypatch):
    _mock_membership(monkeypatch)
    mixed = pd.DataFrame([
        {"spotify_track_id": "good1", "track_name": "A", "artist_names": "X"},
        {"spotify_track_id": None, "track_name": "local", "artist_names": "X"},
        {"spotify_track_id": "good2", "track_name": "B", "artist_names": "X"},
    ])
    monkeypatch.setattr("src.webapp.app.fetch_playlist_tracks", lambda pid, c: mixed)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == ["good1", "good2"]  # the None row dropped


def test_analyze_rejects_non_member_playlist(client, monkeypatch):
    _mock_membership(monkeypatch)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr("src.webapp.app.fetch_playlist_tracks",
                        lambda pid, c: (_ for _ in ()).throw(AssertionError("no fetch")))
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.post("/playlists/theirs1/analyze", follow_redirects=False)  # stranger's
    assert r.status_code == 303 and r.headers["location"] == "/playlists"
    assert fake.enqueued == []  # membership gate blocked the fetch + enqueue


def test_queue_page_public_lists_jobs_and_eta(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'q.db'}")
    tc.remember_meta([{"spotify_track_id": "qq1", "track_name": "Waiting Song",
                       "artist_names": "Band"}])
    tc.enqueue(["qq1"])
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    r = client.get("/queue")  # anon — same public posture as /library
    assert r.status_code == 200
    assert "Waiting Song" in r.text and "min" in r.text
    assert 'http-equiv="refresh"' in r.text  # self-refreshing while non-empty


def test_queue_page_empty_state(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'qe.db'}")
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    r = client.get("/queue")
    assert r.status_code == 200 and "queue is empty" in r.text
    assert 'http-equiv="refresh"' not in r.text  # no pointless reloads


def test_analyze_guest_and_no_scope_blocked(client, monkeypatch):
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    # guest → home, no enqueue
    client.cookies.set(config.SESSION_COOKIE, _seed_session(guest=True))
    g = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert g.status_code == 303 and g.headers["location"] == "/"
    # authed but pre-scope token → re-consent, no enqueue.
    # (clear first: the response above also set the cookie, and two same-name
    # jar entries are sent in platform-dependent order — flaked on CI Linux)
    client.cookies.clear()
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope="user-top-read"))
    n = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert n.status_code == 303 and n.headers["location"] == "/playlists"
    assert fake.enqueued == []
