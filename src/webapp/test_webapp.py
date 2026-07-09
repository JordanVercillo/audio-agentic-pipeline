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


# ── cache-sourced taste logic (Epic A slice 3) ─────────────────────────────
def _feat(tempo, rms=0.20, cent=2100.0):
    return {"tempo_bpm": tempo, "rms_mean": rms, "spectral_centroid_mean": cent,
            "zcr_mean": 0.05, "harmonic_ratio": 0.8}


def test_absolute_profile_bands():
    from .taste import absolute_profile
    prof = absolute_profile([_feat(128), _feat(132)])
    assert prof["n"] == 2 and prof["highlights"]
    assert "upbeat" in prof["message"]  # 130 bpm → upbeat band
    assert absolute_profile([]) is None


def test_drift_over_rows_finite_when_windows_differ():
    from .taste import drift_over_rows
    d = drift_over_rows({
        "short_term": [_feat(120), _feat(122)],
        "long_term": [_feat(140), _feat(142)],
    })
    assert d is not None and math.isfinite(d["score"])
    assert d["n_short"] == 2 and d["n_long"] == 2


def test_drift_over_rows_insufficient_returns_none():
    from .taste import drift_over_rows
    assert drift_over_rows({"short_term": [_feat(120)], "long_term": [_feat(140)]}) is None


def test_track_summary_and_radar_svg():
    from .taste import radar_svg, track_summary
    s = track_summary({"tempo_bpm": 128, "rms_mean": 0.20, "spectral_centroid_mean": 2400})
    assert s["tempo"] == "128 bpm" and s["brightness"] == "2400 Hz"
    assert track_summary(None) is None
    svg = radar_svg({"tempo_bpm": 128, "rms_mean": 0.20, "spectral_centroid_mean": 2400})
    assert svg.startswith("<svg") and "polygon" in svg and "Tempo" in svg


def test_loudness_svg():
    from .taste import loudness_svg
    svg = loudness_svg([-40.0, -22.0, -8.0, -12.0, -6.0])
    assert svg.startswith("<svg") and "loud-area" in svg and "loud-line" in svg
    assert "-6 dB" in svg and "-40 dB" in svg          # honest axis labels (max/min)
    assert "start" in svg and "end" in svg
    assert loudness_svg(None) == "" and loudness_svg([-3.0]) == ""  # nothing to draw


def test_fade_bounds_and_shading():
    from .taste import fade_bounds, loudness_svg
    # fade-in (4 pts), sustained (12), fade-out (3)
    curve = [-50, -40, -30, -20] + [-10] * 12 + [-25, -35, -45]
    fin, fout = fade_bounds(curve)
    assert fin is not None and 0.10 < fin < 0.35      # fade-in ends ~1/5 in
    assert fout is not None and 0.75 < fout < 0.95    # fade-out starts near the end
    assert fade_bounds([-10] * 20) == (None, None)    # constant level → no fades
    assert fade_bounds([-10, -10]) == (None, None)    # too short
    svg = loudness_svg(curve)
    assert "loud-fade" in svg and "fade in" in svg and "fade out" in svg
    assert "loud-fade" not in loudness_svg([-10] * 20)  # no fade → no shading


# ── deep-dive routes (Epic B) ──────────────────────────────────────────────
def test_song_unauthenticated_redirects(client):
    r = client.get("/song/x", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_song_deep_dive_renders_features_and_similar(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'c.db'}")
    tc.upsert("sng1", _feat(128), loudness_curve=[-38.0, -20.0, -9.0, -6.0])
    tc.upsert("sng2", _feat(130))
    tc.remember_meta([{"spotify_track_id": "sng1", "track_name": "Hush", "artist_names": "Muse"},
                      {"spotify_track_id": "sng2", "track_name": "Other", "artist_names": "Band"}])
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=None))
    r = client.get("/song/sng1")
    assert r.status_code == 200
    assert "Hush" in r.text and "<svg" in r.text          # name + radar
    assert "Songs like this" in r.text and "Other" in r.text  # nearest neighbor
    assert "loud-line" in r.text and "Loudness over time" in r.text  # F-v2 curve rendered


def test_spectrogram_404_when_missing(client):
    assert client.get("/spectrogram/nope").status_code == 404


def test_spectrogram_serves_png(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.webapp.app._SPECTROGRAM_DIR", tmp_path)
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    r = client.get("/spectrogram/pic")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


# ── analytics view logic (Epic C) ──────────────────────────────────────────
def test_acoustic_signature_ranks_the_extreme_feature():
    from .analytics import acoustic_signature
    population = [_feat(t) for t in (90, 100, 110, 120, 130, 140)]
    user = [_feat(150), _feat(155)]  # much faster than the population
    sig = acoustic_signature(user, population)
    assert sig and sig[0]["feature"] == "Tempo"
    assert sig[0]["z"] > 0 and sig[0]["word"] == "faster"
    assert acoustic_signature([], population) == []


def test_cluster_composition_movement_sentence():
    from .analytics import cluster_composition
    labels = {"0": "Loud · Fast", "1": "Quiet · Slow"}
    comp = cluster_composition(
        {"short_term": [0, 0, 0, 1], "long_term": [0, 1, 1, 1]}, labels)
    assert comp["windows"]["short_term"][0]["label"] == "Loud · Fast"
    assert "Loud · Fast" in comp["movement"] and "toward" in comp["movement"]
    # identical windows → no movement story
    same = cluster_composition({"short_term": [0, 1], "long_term": [0, 1]}, labels)
    assert same["movement"] is None


def test_scatter_svg_layers_user_over_population():
    from .analytics import scatter_svg
    population = [{"id": f"p{i}", "x": float(i), "y": float(i % 3), "cluster_id": i % 2}
                  for i in range(8)]
    user = [dict(population[0], name="Mine", artist="Me")]
    svg = scatter_svg(population, user)
    assert svg.startswith("<svg") and 'stroke="#171a21"' in svg  # ringed user dot
    assert "<title>Mine — Me</title>" in svg
    assert scatter_svg(population[:2], []) is None  # too few points


# ── taste archetype (Epic D) ───────────────────────────────────────────────
def test_derive_archetype_matrix():
    from .archetype import derive_archetype
    labels = {"0": "Bright · Noisy", "1": "Dark · Smooth", "2": "Loud · Fast"}
    sig = [{"feature": "Tempo", "word": "faster", "z": 1.3}]

    loyal = derive_archetype({"short_term": [0, 0, 0], "long_term": [0, 0, 0, 1]},
                             labels, {"score": 0.12}, sig)
    assert loyal["name"] == "The Anchored Loyalist"
    assert loyal["home"] == "Bright · Noisy" and loyal["motion"] == "Anchored"
    assert any("86%" in e for e in loyal["evidence"])  # 6/7 in one sound
    assert any("+1.3σ" in e for e in loyal["evidence"])

    eclectic = derive_archetype(
        {"short_term": [0, 1, 2], "long_term": [0, 1, 2]}, labels, {"score": 0.5}, [])
    assert eclectic["name"] == "The Roaming Eclectic"

    dual = derive_archetype({"short_term": [0, 0, 1, 1, 0, 1, 2]}, labels,
                            {"score": 0.7}, [])
    assert dual["breadth"] == "Dualist" and dual["motion"] == "Shape-shifting"

    no_drift = derive_archetype({"short_term": [0, 0, 0, 0]}, labels, None, [])
    assert no_drift["name"] == "The Loyalist" and no_drift["motion"] is None

    assert derive_archetype({"short_term": []}, labels, None, []) is None


def _taste_d() -> dict:
    # _TASTE is defined later in this module; resolve it at call time.
    return dict(_TASTE, **{
        "archetype": {"name": "The Anchored Loyalist", "home": "Bright · Noisy",
                      "home_color_id": 0, "breadth": "Loyalist", "motion": "Anchored",
                      "evidence": ["home sound “Bright · Noisy” — 86% of your top songs",
                                   "86% of your top songs live in one sound"]},
        "clusters": {"windows": {"short_term": [{"label": "Bright · Noisy", "share": 80}]},
                     "movement": None},
        "signature": [{"feature": "Tempo", "word": "faster", "z": 1.3}],
    })


def test_rag_grounding_includes_archetype_clusters_signature():
    from .rag import _grounding_text
    txt = _grounding_text(_taste_d(), {})
    assert "The Anchored Loyalist" in txt
    assert "Sound buckets (short_term): 80% “Bright · Noisy”." in txt
    assert "Tempo faster (+1.3σ)" in txt


def test_classify_deterministic_fallback(monkeypatch):
    from .rag import TasteRAG
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = TasteRAG().classify(_taste_d())
    assert res["source"] == "fallback" and res["name"] == "The Anchored Loyalist"
    assert "Bright · Noisy" in res["narrative"] and "Muse" in res["narrative"]
    assert res["narrative"].count(".") >= 2  # sentences, not a fragment


def test_classify_llm_grounded(monkeypatch):
    import types

    from .rag import TasteRAG
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured: dict = {}

    class FakeClient:
        def __init__(self, api_key=None):
            def create(**kw):
                captured.update(kw)
                payload = ('{"thoughts": "grounded", '
                           '"narrative": "You live in bright, noisy songs.", '
                           '"cited": ["Bright · Noisy"]}')
                return types.SimpleNamespace(
                    stop_reason="end_turn",
                    content=[types.SimpleNamespace(type="text", text=payload)])
            self.messages = types.SimpleNamespace(create=create)

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    res = TasteRAG(model="claude-opus-4-8").classify(_taste_d())
    assert res["source"] == "llm" and "bright" in res["narrative"]
    assert res["name"] == "The Anchored Loyalist"          # name stays deterministic
    assert res["cited"] == ["Bright · Noisy"]              # A2 citations
    assert "The Anchored Loyalist" in captured["system"]   # model told the archetype
    assert '"narrative"' in captured["system"]             # contract in the prompt
    assert "Bright · Noisy" in captured["messages"][0]["content"]  # grounded


def test_classify_without_archetype_is_none():
    from .rag import TasteRAG
    assert TasteRAG().classify({"profile": {}})["source"] == "none"


def test_classify_route_renders_profile(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    from ..store.clusters import train_song_clusters
    from ..store.test_clusters import _blob_a, _blob_b

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'cd.db'}")
    for i in range(6):
        tc.upsert(f"a{i}", _blob_a(i))
        tc.upsert(f"b{i}", _blob_b(i))
    tc.remember_meta([{"spotify_track_id": f"{p}{i}", "track_name": f"T{p}{i}",
                       "artist_names": "Muse"} for p in "ab" for i in range(6)])
    assert train_song_clusters(tc, coords="pca") is not None
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)

    taste = {"range_ids": {"short_term": ["b0", "b1", "b2"],
                           "long_term": ["b3", "b4", "a0"]},
             "drift": {"score": 0.2, "label": "Moderate drift"},
             "artists": [{"name": "Muse", "genres": "rock"}]}
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=taste))
    r = client.post("/classify")
    assert r.status_code == 200
    assert "Your taste profile" in r.text and "The Drifting" in r.text
    assert "The evidence" in r.text and "Grounded in your data" in r.text


def test_classify_unauthenticated_redirects(client):
    r = client.post("/classify", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


# ── polish pass ─────────────────────────────────────────────────────────────
def test_www_redirects_to_apex(client):
    r = client.get("/", headers={"host": "www.vercilloanalytics.com"},
                   follow_redirects=False)
    assert r.status_code == 301
    loc = r.headers["location"]
    assert "vercilloanalytics.com" in loc and "www." not in loc


def test_www_redirect_preserves_path_and_query(client):
    r = client.get("/explore?f=tempo", headers={"host": "www.vercilloanalytics.com"},
                   follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"].endswith("/explore?f=tempo")


def test_favicon_and_title_present(client):
    r = client.get("/")
    assert 'rel="icon"' in r.text
    assert "<title>Vercillo Analytics — Taste Pilot</title>" in r.text


def test_missing_art_and_avatar_get_placeholders():
    from .app import templates
    ctx = {"authed": True, "track_total": 1, "coverage": None, "profile": None,
           "drift": None,
           "artists": [{"name": "Muse", "genres": "rock", "image": None}],
           "ranges": [{"key": "short_term", "label": "Last 4 weeks", "tracks": [
               {"rank": 1, "name": "Local File", "artist": "X", "id": "t1",
                "art": None, "analyzed": False, "feat": None}]}]}
    html = templates.get_template("dashboard.html").render(**ctx)
    assert 'class="art art-ph"' in html          # music-note tile, not a gap
    assert 'class="avatar avatar-ph"' in html    # initial-letter avatar
    assert ">M</span>" in html                   # Muse → "M"


def test_privacy_page_public_and_honest(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    assert "songs, not people" in r.text          # the design principle
    assert "user-top-read" in r.text              # the only scope
    assert "never stored" in r.text.lower()       # audio posture (D-15)


def test_analytics_unauthenticated_redirects(client):
    r = client.get("/analytics", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_analytics_without_dashboard_redirects(client):
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste={"range_ids": {}}))
    r = client.get("/analytics", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_analytics_renders_clusters_signature_and_map(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    from ..store.clusters import train_artist_clusters, train_song_clusters
    from ..store.test_clusters import _blob_a, _blob_b

    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'an.db'}")
    meta = []
    for i in range(6):
        tc.upsert(f"a{i}", _blob_a(i))
        tc.upsert(f"b{i}", _blob_b(i))
        meta.append({"spotify_track_id": f"a{i}", "track_name": f"Slow {i}",
                     "artist_names": f"CalmArtist{i // 2}"})
        meta.append({"spotify_track_id": f"b{i}", "track_name": f"Fast {i}",
                     "artist_names": f"LoudArtist{i // 2}"})
    tc.remember_meta(meta)
    assert train_song_clusters(tc, coords="pca") is not None
    assert train_artist_clusters(tc) is not None
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)

    taste = {"range_ids": {"short_term": ["b0", "b1", "a0"],
                           "medium_term": ["b1", "b2"],
                           "long_term": ["a0", "a1", "a2"]},
             "artists": [{"name": "LoudArtist0", "genres": ""}]}
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=taste))
    r = client.get("/analytics")
    assert r.status_code == 200
    assert "acoustic signature" in r.text.lower()
    assert "Your taste archetype" in r.text and 'action="/classify"' in r.text  # Epic D card
    assert "cluster-map" in r.text                     # the SVG map rendered
    assert "Artists who sound alike" in r.text and "LoudArtist0" in r.text
    assert 'class="comp-bar"' in r.text                # composition bars


# ── dashboard context: reads the cache, flags analyzed, queues misses ───────
def test_build_dashboard_context(monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'c.db'}")
    for tid, tempo in [("trk0", 120), ("trk1", 122), ("trk2", 140), ("trk3", 142)]:
        cache.upsert(tid, _feat(tempo))  # already-analyzed
    per_range = {
        "short_term": ["trk0", "trk1", "newmiss"],
        "medium_term": ["trk1", "trk2", "newmiss"],
        "long_term": ["trk2", "trk3", "newmiss"],
    }

    def fake_tracks(time_range, limit=20, sp=None):
        ids = per_range[time_range]
        return pd.DataFrame({
            "spotify_track_id": ids, "track_name": [f"S {i}" for i in ids],
            "artist_names": ["A"] * len(ids), "rank": list(range(1, len(ids) + 1)),
            "album_image_url": [f"http://img/{i}.jpg" for i in ids]})

    def fake_artists(time_range="medium_term", limit=12, sp=None):
        return pd.DataFrame({"artist_name": ["Muse"], "genres": ["rock"], "image_url": [None]})

    monkeypatch.setattr("src.webapp.app.fetch_top_tracks", fake_tracks)
    monkeypatch.setattr("src.webapp.app.fetch_top_artists", fake_artists)
    ctx = build_dashboard_context(client=object(), cache=cache)

    assert ctx["ranges"][0]["tracks"][0]["art"] == "http://img/trk0.jpg"  # album art
    flags = {t["id"]: t["analyzed"] for t in ctx["ranges"][0]["tracks"]}
    assert flags == {"trk0": True, "trk1": True, "newmiss": False}  # cache hits vs miss
    assert ctx["coverage"] == {"analyzed": 4, "total": 5, "analyzing": 1}
    assert ctx["profile"]["n"] == 4  # absolute profile over the 4 analyzed songs
    assert ctx["drift"] is not None and math.isfinite(ctx["drift"]["score"])
    assert [a["name"] for a in ctx["artists"]] == ["Muse"]
    # the miss was queued for extraction
    assert cache.job_status(["newmiss"])["queued"] == 1


# ── routes ─────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_index_renders_login(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Log in with Spotify" in r.text
    # invite-only demo: logged-out visitors see how to request a seat
    assert "jordan@vercilloanalytics.com" in r.text and "5 users" in r.text


def test_error_page_offers_invite_contact(client):
    # e.g. a not-allowlisted Spotify account bounced back from the authorize page
    r = client.get("/callback?error=access_denied")
    assert r.status_code == 400
    assert "jordan@vercilloanalytics.com" in r.text


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
    assert "jordan@vercilloanalytics.com" not in authed_html  # invite card is for visitors
    anon_html = env.get_template("index.html").render(authed=False)
    assert "Log out" not in anon_html and "Log in with Spotify" in anon_html


def test_login_redirects_to_spotify(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert "accounts.spotify.com" in loc and "code_challenge=" in loc
    assert "client_secret" not in loc.lower()  # D-8


# ── RAG /ask (slice 2, updated for cache-sourced profile in slice 3) ────────
_TASTE = {
    "coverage": {"analyzed": 12, "total": 15, "analyzing": 3},
    "profile": {"n": 12, "highlights": ["Tempo: 128 bpm — upbeat", "Energy: 0.21 — moderate"],
                "message": "Across your 12 analyzed tracks: upbeat tempo, moderate energy, "
                           "bright brightness."},
    "drift": {"label": "Moderate drift (exploring new sounds)", "score": 0.21,
              "n_short": 20, "n_long": 20},
    "artists": [{"name": "Muse", "genres": "rock, alternative"}],
    "ranges": [{"label": "Last 4 weeks",
                "tracks": [{"name": "Hush", "artist": "Muse", "analyzed": True}]}],
}


def test_rag_grounding_text_includes_facts():
    from .rag import _grounding_text
    txt = _grounding_text(_TASTE, {"tempo_bpm": "beats per minute"})
    assert "12 of 15" in txt and "upbeat tempo" in txt  # coverage + absolute profile
    assert "Muse" in txt and "Moderate drift" in txt and "tempo_bpm" in txt


def test_rag_fallback_grounds_on_data_no_key(monkeypatch):
    from .rag import TasteRAG
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = TasteRAG().answer("what's my vibe lately?", _TASTE)
    assert res["source"] == "fallback"
    assert "Muse" in res["answer"] and "analyzed tracks" in res["answer"]
    assert "**" not in res["answer"]  # plain prose, no markdown


def test_rag_llm_path_grounds_and_uses_model(monkeypatch):
    import types

    from .rag import TasteRAG
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured: dict = {}

    class FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            payload = ('{"thoughts": "the data shows indie", '
                       '"answer": "Your recent vibe is upbeat indie.", '
                       '"cited": ["Muse"]}')
            return types.SimpleNamespace(
                stop_reason="end_turn",
                content=[types.SimpleNamespace(type="text", text=payload)])

    class FakeClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    res = TasteRAG(model="claude-opus-4-8").answer("what's my vibe?", _TASTE)
    assert res["source"] == "llm" and "indie" in res["answer"].lower()
    assert res["cited"] == ["Muse"]                        # A2: machine-checkable citations
    assert '"thoughts"' in captured["system"]              # contract in the prompt
    assert captured["model"] == "claude-opus-4-8" and captured["max_tokens"] == 1024
    prompt = captured["messages"][0]["content"]
    assert "Muse" in prompt and "Moderate drift" in prompt  # grounded on their data


def test_rag_llm_unparseable_reply_falls_back(monkeypatch):
    import types

    from .rag import TasteRAG
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class FakeClient:
        def __init__(self, api_key=None):
            self.messages = types.SimpleNamespace(
                create=lambda **kw: types.SimpleNamespace(
                    stop_reason="end_turn",
                    content=[types.SimpleNamespace(type="text", text="just prose, no json")]))

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    res = TasteRAG().answer("...", _TASTE)
    assert res["source"] == "fallback" and "Muse" in res["answer"]  # logged + degraded, never fake


def test_rag_llm_refusal_falls_back(monkeypatch):
    import types

    from .rag import TasteRAG
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class FakeClient:
        def __init__(self, api_key=None):
            self.messages = types.SimpleNamespace(
                create=lambda **kw: types.SimpleNamespace(stop_reason="refusal", content=[]))

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    res = TasteRAG().answer("...", _TASTE)
    assert res["source"] == "fallback" and "Muse" in res["answer"]


def _seed_session(taste=None):
    from .app import _signer, _store
    sid = _store.new()
    sess = _store.get(sid)
    sess["token"] = {"access_token": "x"}  # authenticated
    if taste is not None:
        sess["taste"] = taste
    return _signer.sign(sid)


def test_ask_unauthenticated_redirects_home(client):
    r = client.post("/ask", data={"q": "hi"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_ask_without_dashboard_redirects_to_dashboard(client):
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=None))
    r = client.post("/ask", data={"q": "hi"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_ask_returns_grounded_answer(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=_TASTE))
    r = client.post("/ask", data={"q": "what is my vibe lately?"})
    assert r.status_code == 200
    assert "vibe lately" in r.text and "Muse" in r.text  # question echoed + grounded answer
