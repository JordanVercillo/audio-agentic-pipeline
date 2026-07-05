"""
test_webapp.py — synthetic tests for the P8 pilot (SPEC P8).

No network, no real Spotify, no secrets — the token exchange is monkeypatched
and the corpus is synthetic. Runs in the existing `lint-and-test` CI job.
"""

from __future__ import annotations

import math
import time

import pandas as pd
import pytest
from spotipy.oauth2 import SpotifyPKCE

from . import auth_web, config
from .app import build_dashboard_context, create_app
from .featurestore import FeatureStore
from .sessions import CookieSigner, SessionStore

_CLIENT_ID = "test_public_client_id"


@pytest.fixture(autouse=True)
def _client_id_env(monkeypatch):
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("WEBAPP_REDIRECT_URI", "http://127.0.0.1:8000/callback")


# ── session-scoped PKCE ────────────────────────────────────────────────────
def test_authorize_url_stashes_pkce_and_leaks_no_secret():
    session: dict = {}
    url = auth_web.build_authorize_url(session)
    assert "accounts.spotify.com" in url
    assert f"client_id={_CLIENT_ID}" in url
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "state=" in url
    # D-8: PKCE never carries a client secret.
    assert "client_secret" not in url.lower()
    pkce = session["pkce"]
    assert pkce["verifier"] and pkce["challenge"] and pkce["state"]


def test_exchange_rejects_state_mismatch_csrf():
    session: dict = {}
    auth_web.build_authorize_url(session)
    with pytest.raises(auth_web.AuthError, match="State mismatch"):
        auth_web.exchange_code(session, code="abc", state="not-the-state")


def test_exchange_without_inflight_login_raises():
    with pytest.raises(auth_web.AuthError, match="No in-flight login"):
        auth_web.exchange_code({}, code="abc", state="whatever")


def test_exchange_success_stores_token(monkeypatch):
    def fake_token(self, code=None, check_cache=True):
        self.cache_handler.save_token_to_cache(
            {"access_token": "tok123", "token_type": "Bearer",
             "expires_in": 3600, "scope": config.SCOPES})
        return "tok123"

    monkeypatch.setattr(SpotifyPKCE, "get_access_token", fake_token)
    session: dict = {}
    auth_web.build_authorize_url(session)
    state = session["pkce"]["state"]
    token = auth_web.exchange_code(session, code="realcode", state=state)
    assert token["access_token"] == "tok123"
    assert auth_web.is_authenticated(session)
    assert "pkce" not in session  # in-flight cleared


# ── session store ──────────────────────────────────────────────────────────
def test_session_store_ttl_expiry():
    store = SessionStore(ttl_seconds=0)  # already expired on next tick
    sid = store.new()
    time.sleep(0.01)
    assert store.get(sid) is None


def test_session_store_rotate_preserves_data():
    store = SessionStore(ttl_seconds=60)
    sid = store.new()
    store.get(sid)["token"] = {"access_token": "x"}
    new = store.rotate(sid)
    assert new != sid
    assert store.get(sid) is None
    assert store.get(new)["token"] == {"access_token": "x"}


def test_cookie_signer_roundtrip_and_tamper():
    signer = CookieSigner("secret-key")
    token = signer.sign("sid-123")
    assert signer.unsign(token) == "sid-123"
    assert signer.unsign(token + "x") is None  # tampered
    assert signer.unsign(None) is None


# ── feature store (the bridge-key join) ────────────────────────────────────
@pytest.fixture
def corpus_dir(tmp_path):
    ids = [f"trk{i}" for i in range(5)]
    fact = pd.DataFrame({
        "spotify_track_id": ids,
        "track_name": [f"Song {i}" for i in range(5)],
        "primary_artist_name": [f"Artist {i}" for i in range(5)],
        "time_range": ["short_term"] * 5,
        "tempo_bpm": [120, 122, 118, 124, 121],
        "rms_mean": [0.20, 0.21, 0.19, 0.22, 0.20],
        "spectral_centroid_mean": [2000, 2100, 1950, 2050, 2000],
    })
    fact.to_parquet(tmp_path / "fact_listening_features.parquet")
    pd.DataFrame({
        "spotify_track_id": ids,
        "genre_bucket": ["Rock", "Rock", "Jazz", "Rock", "Rock"],
    }).to_parquet(tmp_path / "cluster_assignments.parquet")
    return tmp_path


def test_featurestore_overlap_and_insight(corpus_dir):
    fs = FeatureStore(corpus_dir)
    prof = fs.profile(["trk0", "trk1", "trk3", "unknown_x"])
    assert prof["corpus_size"] == 5
    assert prof["overlap_count"] == 3
    assert set(prof["overlap_ids"]) == {"trk0", "trk1", "trk3"}
    assert prof["dominant_genre"] == "Rock"
    assert prof["highlights"]  # tempo/energy/brightness phrases
    assert len(prof["matched"]) == 3
    # rms_mean (~0.2) must not round to "0" — adaptive formatting (bugfix)
    assert any("0.2" in h for h in prof["highlights"])


def test_featurestore_zero_overlap_is_graceful(corpus_dir):
    fs = FeatureStore(corpus_dir)
    prof = fs.profile(["nope1", "nope2"])
    assert prof["overlap_count"] == 0
    assert prof["highlights"] == []
    assert "metadata view" in prof["message"]


def test_featurestore_missing_warehouse_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        FeatureStore(tmp_path)


def test_drift_profile(corpus_dir):
    fs = FeatureStore(corpus_dir)
    d = fs.drift_profile({
        "short_term": ["trk0", "trk1"],
        "medium_term": ["trk1", "trk2"],
        "long_term": ["trk3", "trk4"],
    })
    assert d is not None and math.isfinite(d["score"])
    assert d["n_short"] == 2 and d["n_long"] == 2 and d["label"]


def test_drift_profile_insufficient_overlap_returns_none(corpus_dir):
    fs = FeatureStore(corpus_dir)
    # <2 overlapping tracks per window ⇒ too noisy ⇒ None (honest)
    assert fs.drift_profile({"short_term": ["trk0"], "long_term": ["trk1"]}) is None


# ── dashboard context (with a fake Spotify client) ─────────────────────────
def test_build_dashboard_context(monkeypatch, corpus_dir):
    per_range = {
        "short_term": ["trk0", "trk1", "outsider"],
        "medium_term": ["trk1", "trk2", "outsider"],
        "long_term": ["trk2", "trk3", "outsider"],
    }

    def fake_tracks(time_range, limit=20, sp=None):
        ids = per_range[time_range]
        return pd.DataFrame({
            "spotify_track_id": ids,
            "track_name": [f"Song {i}" for i in ids],
            "artist_names": ["A"] * len(ids),
            "rank": list(range(1, len(ids) + 1)),
            "album_image_url": [f"http://img/{i}.jpg" for i in ids],
        })

    def fake_artists(time_range="medium_term", limit=12, sp=None):
        return pd.DataFrame({
            "artist_name": ["Muse", "Toploader"],
            "genres": ["rock, alt", ""],
            "image_url": ["http://a/muse.jpg", None],
        })

    monkeypatch.setattr("src.webapp.app.fetch_top_tracks", fake_tracks)
    monkeypatch.setattr("src.webapp.app.fetch_top_artists", fake_artists)
    ctx = build_dashboard_context(client=object(), store=FeatureStore(corpus_dir))

    assert len(ctx["ranges"]) == 3
    # album art carried through to the track view-model
    assert ctx["ranges"][0]["tracks"][0]["art"] == "http://img/trk0.jpg"
    # overlap flags (short_term: trk0, trk1 in corpus; outsider not)
    flags = {t["id"]: t["in_corpus"] for t in ctx["ranges"][0]["tracks"]}
    assert flags == {"trk0": True, "trk1": True, "outsider": False}
    # top-artists section (genres — which Spotify exposes for artists, not tracks)
    assert [a["name"] for a in ctx["artists"]] == ["Muse", "Toploader"]
    assert ctx["artists"][0]["genres"] == "rock, alt"
    # per-visitor taste drift computed (short vs long overlap differ → finite)
    assert ctx["drift"] is not None and math.isfinite(ctx["drift"]["score"])


# ── routes ─────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_index_renders_login(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Log in with Spotify" in r.text


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_dashboard_unauthenticated_redirects_home(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_header_reflects_auth_state():
    """The nav shows Log out when authed, Log in when not (base.html header)."""
    from .app import templates
    env = templates.env
    authed_html = env.get_template("index.html").render(authed=True)
    assert "Log out" in authed_html and "/dashboard" in authed_html
    anon_html = env.get_template("index.html").render(authed=False)
    assert "Log out" not in anon_html and "Log in with Spotify" in anon_html


def test_login_redirects_to_spotify(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert "accounts.spotify.com" in loc and "code_challenge=" in loc
    assert "client_secret" not in loc.lower()  # D-8
