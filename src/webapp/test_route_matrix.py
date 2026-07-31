"""
test_route_matrix.py — QA-2 layer 3: every route x every persona, as a table.

The route tests that existed before this file were per-FEATURE and scattered, so
access-gate coverage was not PROVABLE. That gap is what produced bug A7 (the
D-56 owner gate wrapped the whole analyzed block and hid the owner's own repair
tools) and it left 17 gate cells across 12 routes with no assertion at all —
four of them on corpus-mutating writes, including `POST /song/{id}/repair-upload`
which had no test of any kind.

Three properties make this a security artifact rather than a status-code diary:

  1. COVERAGE IS ENFORCED, not aspirational. The matrix's (path, method) set must
     EQUAL the app's registered set, so a new route fails as missing and a
     deleted one fails as stale.
  2. THE `effects` COLUMN. `POST /song/{id}/repair-link` returns the SAME
     303 -> /song/{id} to anon, guest, user and owner. Status and Location cannot
     tell a blocked request from an executed one; only "did the engine run"
     can. Every anon and guest cell declares effects=NONE, which turns "PKCE
     means no app token exists, so a guest live-call is the owner's credential
     leaking" into an assertion instead of a comment.
  3. PERSONAS PROVE THEMSELVES. Journal #51: a duplicate `va_sid` in the httpx
     jar meant "log in as someone else" silently kept the previous user on CI
     for twelve commits. A fresh client per cell removes the shared jar, and the
     sid echo asserts which session the SERVER actually resolved.

Synthetic only — tmp sqlite cache, stubbed marts/LLM/fetchers — so it runs in
the existing CI job with no corpus, no Ollama and no network.
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import pandas as pd
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from . import config
from .app import create_app

OWNER_ID = "jordan_id"
ANON, GUEST, USER, OWNER = "anon", "guest", "user", "owner"
PERSONAS = (ANON, GUEST, USER, OWNER)
# NOTE ON NAMING: `USER` is a logged-in NON-OWNER pilot user. The app's own
# `_is_viewer()` means GUEST-or-above, which is a different set — so this file
# never says "viewer" for a persona.

TRACK = "sng1"
ARTIST = "ar1AAAAAA"
PLAYLIST = "pl1"

# ── markers ──────────────────────────────────────────────────────────────────
# A marker is an HTML attribute the app's own behaviour depends on — a form
# action, an href the nav needs, a class the CSS binds. NEVER a sentence: copy
# changes freely, `action="/classify"` cannot change without behaviour changing.
MARKERS = {
    "page_shell": '<link rel="stylesheet" href="/static/style.css">',
    "logout_form": 'action="/logout"',
    "login_cta": 'href="/login"',
    "error_page": "Something went sideways",
    "ask_form": 'action="/ask"',
    "classify_form": 'action="/classify"',
    "chat_form": 'action="/chat"',
    "needs_source_tab": 'href="/library?filter=needs-source"',
    "repair_link_form": f'action="/song/{TRACK}/repair-link"',
    "repair_upload_form": f'action="/song/{TRACK}/repair-upload"',
}
# Auto-applied to every cell expecting a 200 HTML page, so "200" can never mean
# "an error page rendered with a 200" or "a truncated shell".
GLOBAL_REQUIRE_HTML = ("page_shell",)
GLOBAL_FORBID_HTML = ("error_page",)

# effect names the `wiring` fixture counts
SPOTIFY, ENQUEUE, LLM, REPAIR = "spotify", "enqueue", "llm", "repair"
NONE: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Expect:
    status: int
    location: Optional[str] = None
    location_has: tuple[str, ...] = ()
    require: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    json_has: tuple[tuple[str, Any], ...] = ()
    forbid_text: tuple[str, ...] = ()
    effects: frozenset[str] = NONE


@dataclass(frozen=True)
class Row:
    path: str            # the REGISTERED path — the coverage key
    method: str
    url: str             # the concrete URL to call
    decision: str        # the decision this row encodes
    by: dict[str, Expect]
    rotates: bool = False
    data: Optional[dict] = None
    files: Optional[dict] = None
    html: bool = True    # participates in the global HTML invariants
    skip_oracle: str = ""


def _gate(to: str) -> Expect:
    """A blocked request: redirect home, and NOTHING may have run."""
    return Expect(303, location=to, effects=NONE)


MATRIX: list[Row] = [
    Row("/", "GET", "/", "public landing", {
        ANON: Expect(200, require=("login_cta",), forbid=("logout_form",)),
        GUEST: Expect(200),
        USER: Expect(200, require=("logout_form",)),
        OWNER: Expect(200, require=("logout_form",))}),

    Row("/login", "GET", "/login", "D-8 PKCE, no secret", {
        p: Expect(307, location_has=("accounts.spotify.com", "code_challenge=",
                                     "state="),
                  forbid_text=("client_secret",))
        for p in PERSONAS}, html=False),

    Row("/guest", "GET", "/guest", "H7 demo entry, never clobbers an authed session", {
        p: Expect(303, location="/dashboard", effects=NONE) for p in PERSONAS},
        html=False),

    Row("/callback", "GET", "/callback?code=abc&state=evil", "CSRF state gate", {
        p: Expect(400, require=("error_page",), effects=NONE) for p in PERSONAS}),

    Row("/dashboard", "GET", "/dashboard", "H7 viewer split", {
        ANON: _gate("/"),
        GUEST: Expect(200, forbid=("ask_form",), effects=NONE),
        USER: Expect(200, require=("ask_form",), effects=frozenset({SPOTIFY, ENQUEUE})),
        OWNER: Expect(200, effects=frozenset({SPOTIFY, ENQUEUE}))}),

    Row("/status", "GET", "/status", "authed JSON", {
        ANON: Expect(200, json_has=(("authed", False),), effects=NONE),
        GUEST: Expect(200, json_has=(("authed", False),), effects=NONE),
        USER: Expect(200, json_has=(("authed", True),)),
        OWNER: Expect(200, json_has=(("authed", True),))}, html=False),

    Row("/ask", "POST", "/ask", "authed + token action", {
        ANON: _gate("/"),
        GUEST: _gate("/"),
        USER: Expect(200, effects=frozenset({LLM})),
        OWNER: Expect(200, effects=frozenset({LLM}))}, data={"q": "what is my tempo"}),

    Row("/chat", "GET", "/chat", "K1c viewer-gated", {
        ANON: _gate("/"),
        GUEST: Expect(200, require=("chat_form",), effects=frozenset({LLM})),
        USER: Expect(200, require=("chat_form",), effects=frozenset({LLM})),
        OWNER: Expect(200, effects=frozenset({LLM}))}),

    Row("/chat", "POST", "/chat", "K1c viewer-gated", {
        ANON: _gate("/"),
        GUEST: Expect(303, location="/chat", effects=frozenset({LLM})),
        USER: Expect(303, location="/chat", effects=frozenset({LLM})),
        OWNER: Expect(303, location="/chat", effects=frozenset({LLM}))},
        data={"q": "hello"}, html=False),

    Row("/analytics", "GET", "/analytics", "viewer-gated", {
        ANON: _gate("/"),
        GUEST: Expect(200, forbid=("classify_form",), effects=NONE),
        USER: Expect(200, require=("classify_form",)),
        OWNER: Expect(200, require=("classify_form",))}),

    Row("/classify", "POST", "/classify", "authed + token action", {
        ANON: _gate("/"),
        GUEST: _gate("/"),
        USER: Expect(200, effects=frozenset({LLM})),
        OWNER: Expect(200, effects=frozenset({LLM}))}),

    # R1 (P4.7.2): PUBLIC — the index is built from the CORPUS, not from a
    # visitor's taste, so it carries nothing personal (the same population-only
    # move that made /library public, D-18). The "Your artists" TAB is still
    # viewer-only and falls back to "all" for anon.
    Row("/artists", "GET", "/artists", "D-18 public corpus index", {
        ANON: Expect(200, effects=NONE),
        GUEST: Expect(200, effects=NONE),
        USER: Expect(200),
        OWNER: Expect(200)}),

    # R2: PUBLIC too — the discography and acoustic profile are corpus facts.
    # The listening-derived list and the borrowed-time live top-10 degrade to
    # honest captions rather than gating the page (the live call stays authed:
    # PKCE means a guest fetch would be the owner's token leaking).
    Row("/artist/{artist_id}", "GET", f"/artist/{ARTIST}", "D-18 public artist page", {
        ANON: Expect(200, effects=NONE),
        GUEST: Expect(200, effects=NONE),
        USER: Expect(200, effects=frozenset({SPOTIFY})),
        OWNER: Expect(200, effects=frozenset({SPOTIFY}))}),

    Row("/artist/{artist_id}/analyze", "POST", f"/artist/{ARTIST}/analyze",
        "authed + corpus write", {
            ANON: _gate("/"),
            GUEST: _gate("/"),
            USER: Expect(303, location=f"/artist/{ARTIST}",
                         effects=frozenset({SPOTIFY, ENQUEUE})),
            OWNER: Expect(303, location=f"/artist/{ARTIST}",
                          effects=frozenset({SPOTIFY, ENQUEUE}))}, html=False),

    Row("/recommend", "GET", "/recommend", "viewer-gated", {
        ANON: _gate("/"),
        GUEST: Expect(200, effects=NONE),
        USER: Expect(200),
        OWNER: Expect(200)}),

    Row("/explore", "GET", "/explore", "viewer-gated", {
        ANON: _gate("/"),
        GUEST: Expect(200, effects=NONE),
        USER: Expect(200),
        OWNER: Expect(200)}),

    Row("/playlists", "GET", "/playlists", "authed + scope", {
        ANON: _gate("/"),
        GUEST: _gate("/"),
        USER: Expect(200, effects=frozenset({SPOTIFY})),
        OWNER: Expect(200, effects=frozenset({SPOTIFY}))}),

    Row("/playlists/{playlist_id}/analyze", "POST", f"/playlists/{PLAYLIST}/analyze",
        "authed + scope + membership + corpus write", {
            ANON: _gate("/"),
            GUEST: _gate("/"),
            USER: Expect(303, location="/playlists",
                         effects=frozenset({SPOTIFY, ENQUEUE})),
            OWNER: Expect(303, location="/playlists",
                          effects=frozenset({SPOTIFY, ENQUEUE}))}, html=False),

    Row("/queue", "GET", "/queue", "D-40 public", {
        p: Expect(200, effects=NONE) for p in PERSONAS}),

    # THE A7 BUG CLASS, both directions: the owner must SEE the repair queue and
    # nobody else may. Before this row, only the env-unset case was asserted.
    Row("/library", "GET", "/library", "D-18 public + D-56 owner affordance", {
        ANON: Expect(200, forbid=("needs_source_tab",), effects=NONE),
        GUEST: Expect(200, forbid=("needs_source_tab",), effects=NONE),
        USER: Expect(200, forbid=("needs_source_tab",)),
        OWNER: Expect(200, require=("needs_source_tab",))}),

    Row("/song/{track_id}", "GET", f"/song/{TRACK}", "D-18 public + D-56 owner tools", {
        ANON: Expect(200, forbid=("repair_link_form", "repair_upload_form"), effects=NONE),
        GUEST: Expect(200, forbid=("repair_link_form", "repair_upload_form"), effects=NONE),
        USER: Expect(200, forbid=("repair_link_form", "repair_upload_form")),
        OWNER: Expect(200, require=("repair_link_form", "repair_upload_form"))}),

    # D-66: the all-features drill-down is corpus data, so it is PUBLIC on the
    # same terms as /song — and inherits the same D-57 withhold (an unverified
    # source shows nothing here either; 83 numbers presented as fact would be a
    # bigger version of the trust the withhold protects).
    Row("/song/{track_id}/features", "GET", f"/song/{TRACK}/features",
        "D-66 public transparency", {
        ANON: Expect(200, effects=NONE),
        GUEST: Expect(200, effects=NONE),
        USER: Expect(200),
        OWNER: Expect(200)}),

    # V2: we HOST an uploaded file, so serving it publicly is a licensing
    # exposure. A YouTube-sourced track is verifiable via its public link.
    Row("/audio/{track_id}", "GET", f"/audio/{TRACK}", "V2 owner-only playback", {
        ANON: Expect(303, location=f"/song/{TRACK}", effects=NONE),
        GUEST: Expect(303, location=f"/song/{TRACK}", effects=NONE),
        USER: Expect(303, location=f"/song/{TRACK}", effects=NONE),
        OWNER: Expect(404, effects=NONE)}, html=False),  # gate passes, no file retained

    # Identical status AND location for all four personas — only `effects`
    # separates a blocked request from an executed one.
    Row("/song/{track_id}/repair-link", "POST", f"/song/{TRACK}/repair-link",
        "D-56 owner, fail-closed", {
            ANON: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            GUEST: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            USER: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            OWNER: Expect(303, location=f"/song/{TRACK}",
                          effects=frozenset({REPAIR}))},
        data={"url": "https://youtu.be/x"}, html=False),

    Row("/song/{track_id}/repair-upload", "POST", f"/song/{TRACK}/repair-upload",
        "D-56 owner, fail-closed", {
            ANON: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            GUEST: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            USER: Expect(303, location=f"/song/{TRACK}", effects=NONE),
            OWNER: Expect(303, location=f"/song/{TRACK}",
                          effects=frozenset({REPAIR}))},
        files={"file": ("a.mp3", b"ID3fake", "audio/mpeg")}, html=False),

    Row("/spectrogram/{track_id}", "GET", f"/spectrogram/{TRACK}", "D-18 public", {
        p: Expect(404, effects=NONE) for p in PERSONAS}, html=False,
        skip_oracle="public by D-18: 200-vs-404 is intended, not an oracle"),

    Row("/logout", "POST", "/logout", "POST-only, CSRF", {
        p: Expect(303, location="/", effects=NONE) for p in PERSONAS},
        rotates=True, html=False),

    Row("/privacy", "GET", "/privacy", "public disclosure", {
        p: Expect(200, effects=NONE) for p in PERSONAS}),

    Row("/healthz", "GET", "/healthz", "public", {
        p: Expect(200, json_has=(("ok", True),), effects=NONE) for p in PERSONAS},
        html=False),
]


# ── coverage: the matrix must EQUAL the app's route set ──────────────────────
def test_matrix_covers_every_registered_route():
    app = create_app()
    live = {(r.path, m) for r in app.routes if isinstance(r, APIRoute)
            for m in r.methods if m not in ("HEAD", "OPTIONS")}
    covered = {(r.path, r.method) for r in MATRIX}
    assert covered == live, (
        f"NEW route(s) missing from the matrix: {sorted(live - covered)}; "
        f"STALE row(s): {sorted(covered - live)}")
    assert len(live) == 29, "route count changed — update docs/DEDUP_QA_SPEC.md too"


def test_non_apiroute_surface_stays_an_allowlist():
    """A Mount or a bare Starlette route is INVISIBLE to APIRoute enumeration —
    `app.mount("/admin", admin_app)` would leave coverage green with an entire
    un-gated sub-app live. Naming the surface makes that a failure."""
    app = create_app()
    others = {getattr(r, "path", str(r)) for r in app.routes
              if not isinstance(r, APIRoute)}
    assert others == {"/static"}, f"unlisted surface: {others}"


def test_openapi_schema_is_not_served(matrix_app):
    """QA-2: /docs and /redoc were closed but /openapi.json still handed any
    anonymous caller the full surface map — every path including the owner-only
    repair routes, with parameter shapes. The gates hold either way; this keeps
    the map private and matches the intent already in the constructor."""
    client, _ = client_as(matrix_app, ANON)
    assert client.get("/openapi.json").status_code == 404


def test_every_forbidden_marker_is_required_somewhere():
    """THE anti-vacuity guard. If a template refactor renames a marker, every
    `forbid` assertion using it passes trivially — the matrix stays green while
    the gate may now leak. Requiring each forbidden marker to be REQUIRED by
    some other cell means the rename fails loudly there instead."""
    forbidden = {m for r in MATRIX for e in r.by.values() for m in e.forbid}
    required = {m for r in MATRIX for e in r.by.values() for m in e.require}
    assert forbidden <= required, f"unprovable forbids: {sorted(forbidden - required)}"


# ── wiring: patch DATA SOURCES only, never a gate ────────────────────────────
_CLUSTERED = [f"{p}{i}" for p in "ab" for i in range(6)]
_TASTE = {
    "range_ids": {"short_term": [TRACK, *_CLUSTERED[:6]],
                  "long_term": _CLUSTERED[6:]},
    "coverage": {"analyzed": 1, "total": 1, "analyzing": 0},
    "profile": {"n": 1, "highlights": ["Tempo: 120 bpm — steady"],
                "message": "Across your 1 analyzed track: steady tempo."},
    "drift": {"label": "Low drift", "score": 0.1, "n_short": 1, "n_long": 1},
    "artists": [{"name": "Band", "genres": "rock"}],
    "ranges": [{"label": "Last 4 weeks",
                "tracks": [{"name": "Hush", "artist": "Band", "analyzed": True}]}],
}
_FEATURES = {"tempo_bpm": 120.0, "rms_mean": 0.2, "spectral_centroid_mean": 2000.0,
             "spectral_rolloff_mean": 4000.0, "zcr_mean": 0.05, "duration_sec": 200.0,
             "harmonic_ratio": 0.5, "onset_strength_mean": 1.2,
             **{f"mfcc_mean_{i}": float(i) for i in range(5)}}
_DEMO = {"range_ids": {"short_term": [TRACK, *_CLUSTERED[:6]],
                       "long_term": _CLUSTERED[6:]},
         "artists": [{"name": "Band", "genres": "rock"}]}
_CATALOG = pd.DataFrame([
    {"column": "tempo", "tier": "measured", "unit": "bpm", "friendly": "Tempo",
     "description": "Estimated tempo from beat tracking."},
    {"column": "energy", "tier": "derived", "unit": "0-1", "friendly": "Energy",
     "description": "Perceived intensity."}])
_STATS = _CATALOG.assign(
    n=1, mean=0.5, std=0.1, min=0.0, p5=0.1, p25=0.2, p50=0.5, p75=0.8, p95=0.9,
    max=1.0, version="perceptual-v1",
    bin_edges=[[0.0, 0.5, 1.0]] * 2, bin_counts=[[1, 1]] * 2)


def _counting(name: str, fired: collections.Counter, result):
    def _fn(*a, **k):
        fired[name] += 1
        return result() if callable(result) else result
    return _fn


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    """Patch DATA SOURCES ONLY.

    NEVER patch `is_authenticated`, `_is_viewer` or `_is_owner` here — stubbing a
    gate would make all 112 cells a tautology. `test_owner_gate_fails_closed_
    without_env` is the control that flips if someone does it anyway."""
    from ..store.cache import FeatureCache
    from ..store.clusters import train_song_clusters
    from ..store.test_clusters import _blob_a, _blob_b
    from .rag import TasteRAG

    fired: collections.Counter = collections.Counter()
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "test_public_client_id")
    monkeypatch.setenv("WEBAPP_REDIRECT_URI", "http://127.0.0.1:8000/callback")
    monkeypatch.setenv("WEBAPP_OWNER_SPOTIFY_ID", OWNER_ID)

    cache = FeatureCache(f"sqlite:///{tmp_path / 'c.db'}")
    cache.upsert(TRACK, _FEATURES)
    cache.remember_meta([{"spotify_track_id": TRACK, "track_name": "Hush",
                          "artist_names": "Band", "duration_ms": 200000,
                          "primary_artist_id": ARTIST}])
    cache.remember_provenance(spotify_track_id=TRACK, youtube_url="https://youtu.be/x",
                              youtube_title="Hush", match_confidence=0.9)
    cache.remember_artists([{"artist_id": ARTIST, "artist_name": "Band",
                             "genres": "rock"}])
    # A TRAINED cluster model, so /analytics renders its archetype block. Without
    # one the block is absent and "guest must not see the classify form" would
    # pass because the form isn't there for ANYONE — a vacuous gate assertion.
    for i in range(6):
        cache.upsert(f"a{i}", _blob_a(i))
        cache.upsert(f"b{i}", _blob_b(i))
    cache.remember_meta([{"spotify_track_id": f"{p}{i}", "track_name": f"T{p}{i}",
                          "artist_names": "Band"} for p in "ab" for i in range(6)])
    for p in "ab":
        for i in range(6):
            cache.remember_provenance(spotify_track_id=f"{p}{i}",
                                      youtube_url=f"https://youtu.be/{p}{i}")
    assert train_song_clusters(cache, coords="pca") is not None
    real_enqueue = cache.enqueue

    def counting_enqueue(ids):
        fired[ENQUEUE] += 1
        return real_enqueue(ids)
    monkeypatch.setattr(cache, "enqueue", counting_enqueue)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: cache)

    # The D-56 repair queue is read from the re-extract LEDGER ON DISK, and the
    # owner's "Needs source" tab renders only when that queue is non-empty. On
    # this machine the real ledger has entries; on CI the file does not exist,
    # so the owner cell passed locally and failed on CI — the precise
    # works-on-my-box class this matrix exists to eliminate. Supply a ledger
    # with one entry (a track with metadata and deliberately NO provenance, so
    # it is genuinely unresolved) and the cell becomes machine-independent.
    cache.remember_meta([{"spotify_track_id": "needsrc1", "track_name": "No Source",
                          "artist_names": "Band"}])
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(
        {"failed": {"needsrc1": {"error": "no usable source — title mismatch"}}}),
        encoding="utf-8")
    monkeypatch.setattr("src.webapp.app._LEDGER_PATH", ledger)
    # Same discipline for every other path the routes stat: retained owner audio
    # (/audio) and spectrograms (/song). Pointing them at tmp means no cell can
    # read this box's data/ directory and quietly answer differently than CI.
    monkeypatch.setattr("src.webapp.app._OWNER_AUDIO_DIR", tmp_path / "owner_audio")
    monkeypatch.setattr("src.webapp.app._SPECTROGRAM_DIR", tmp_path / "spectrograms")

    for fn, result in (("fetch_top_tracks", lambda: pd.DataFrame()),
                       ("fetch_top_artists", lambda: pd.DataFrame()),
                       ("fetch_artist_top_tracks", lambda: pd.DataFrame()),
                       ("fetch_user_playlists", lambda: pd.DataFrame())):
        monkeypatch.setattr(f"src.webapp.app.{fn}", _counting(SPOTIFY, fired, result))
    # the import walks pages now (it never drains a playlist) — one empty page
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages",
                        _counting(SPOTIFY, fired, lambda: iter([([], True)])))
    monkeypatch.setattr("src.webapp.app.auth_web.client_from_session",
                        lambda s, **k: SimpleNamespace(
                            me=lambda: {"id": s.get("me_id") or "someone"}))

    # Each surface reads a different key off the reply — stub the real shapes so
    # a cell fails on its GATE, never on a mis-shaped fixture.
    reply = {"answer": "steady tempo", "source": "fallback", "model": None,
             "grounding": "", "raw": "", "cited": []}
    for meth in ("answer", "story"):
        monkeypatch.setattr(TasteRAG, meth, _counting(LLM, fired, lambda: dict(reply)))
    monkeypatch.setattr(TasteRAG, "classify", _counting(
        LLM, fired, lambda: {**reply, "narrative": "You are a steady listener."}))
    monkeypatch.setattr("src.store.repair.repair_from_link",
                        _counting(REPAIR, fired, (True, "ok")))
    monkeypatch.setattr("src.store.repair.repair_from_upload",
                        _counting(REPAIR, fired, (True, "ok")))

    # Marts are gitignored and absent on CI, so the explore/recommend surfaces
    # get SHAPED stubs — an empty frame would fail on a missing column and hide
    # the gate behind a 500. Two features is enough for every x/y picker.
    monkeypatch.setattr("src.webapp.app.load_catalog", lambda *a, **k: _CATALOG.copy())
    # load_stats() returns the frame INDEXED BY COLUMN — mirror that exactly, or
    # the stub diverges from production and the surface fails for the wrong reason.
    monkeypatch.setattr("src.webapp.app.load_stats",
                        lambda *a, **k: _STATS.copy().set_index("column"))
    monkeypatch.setattr("src.webapp.app.load_demo_profile", lambda: _DEMO)
    yield SimpleNamespace(cache=cache, fired=fired)


def _seed(persona: str) -> str:
    """Return the RAW sid for a persona (never a pre-signed cookie, so the echo
    assertion can compare what the server resolved)."""
    from .app import _store
    sid = _store.new()
    sess = _store.get(sid)
    if persona is GUEST:
        sess["is_guest"] = True
        sess["taste"] = _TASTE
    elif persona in (USER, OWNER):
        sess["token"] = {"access_token": "x"}
        sess["taste"] = _TASTE
        sess["me_id"] = OWNER_ID if persona is OWNER else "someone_else"
    return sid


def client_as(app, persona: str) -> tuple[TestClient, Optional[str]]:
    """A FRESH client per cell — no jar can be inherited by construction, which
    is journal #51's root cause removed structurally rather than worked around.
    follow_redirects=False so a 303 gate can never silently read as a 200."""
    from .app import _signer
    c = TestClient(app, follow_redirects=False)
    if persona is ANON:
        assert not list(c.cookies.jar)
        return c, None
    sid = _seed(persona)
    c.cookies.set(config.SESSION_COOKIE, _signer.sign(sid))
    jar = [k for k in c.cookies.jar if k.name == config.SESSION_COOKIE]
    assert len(jar) == 1, f"duplicate session cookies: {[(k.domain, k.path) for k in jar]}"
    return c, sid


def _assert_identity_echo(resp, sid, *, rotates: bool):
    """The version-INDEPENDENT proof that the request was served AS this persona:
    the middleware re-sets the cookie with the sid it actually resolved. A
    stale-jar bug shows up here as a different sid — the failure that hid on CI
    for twelve commits while every behavioural assertion passed."""
    from .app import _signer
    raw = resp.cookies.get(config.SESSION_COOKIE)
    if sid is None or raw is None:
        return
    served = _signer.unsign(raw)
    if rotates:
        assert served != sid, "expected a session rotation, got the same id"
    else:
        assert served == sid, f"served session {served!r}, seeded {sid!r}"


@pytest.fixture(scope="module")
def matrix_app():
    return create_app()


_CELLS = [(row, p) for row in MATRIX for p in PERSONAS]


@pytest.mark.parametrize("row,persona", _CELLS,
                         ids=[f"{r.method} {r.path}[{p}]" for r, p in _CELLS])
def test_route_matrix(matrix_app, wiring, row: Row, persona: str):
    exp = row.by[persona]
    client, sid = client_as(matrix_app, persona)
    kwargs: dict[str, Any] = {}
    if row.data:
        kwargs["data"] = row.data
    if row.files:
        kwargs["files"] = row.files
    resp = client.request(row.method, row.url, **kwargs)

    assert resp.status_code == exp.status, (
        f"{row.method} {row.url} as {persona} ({row.decision}): "
        f"expected {exp.status}, got {resp.status_code}")
    if exp.location is not None:
        assert resp.headers.get("location") == exp.location
    for frag in exp.location_has:
        assert frag in resp.headers.get("location", ""), frag
    for frag in exp.forbid_text:
        assert frag not in resp.headers.get("location", "").lower()
        assert frag not in resp.text.lower()

    body = resp.text
    require = tuple(exp.require)
    forbid = tuple(exp.forbid)
    if row.html and exp.status == 200:
        require += GLOBAL_REQUIRE_HTML
        forbid += GLOBAL_FORBID_HTML
    for m in require:
        assert MARKERS[m] in body, f"{row.url} as {persona}: missing marker {m}"
    for m in forbid:
        assert MARKERS[m] not in body, f"{row.url} as {persona}: LEAKED marker {m}"
    for key, val in exp.json_has:
        assert resp.json()[key] == val

    # THE security assertion: status and location cannot distinguish a blocked
    # request from an executed one on the repair routes — this can.
    leaked = set(wiring.fired) - set(exp.effects)
    assert not leaked, (
        f"{row.method} {row.url} as {persona}: side effect(s) {sorted(leaked)} "
        f"fired despite the gate (status {resp.status_code} looked correct)")
    _assert_identity_echo(resp, sid, rotates=row.rotates)


# ── the controls ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("persona,url,marker", [
    (GUEST, "/analytics", "chat_form"),          # guests reach viewer surfaces
    (USER, "/library", "logout_form"),           # authed chrome
    (OWNER, "/library", "needs_source_tab"),     # the owner gate really opens
])
def test_persona_is_really_that_persona(matrix_app, wiring, persona, url, marker):
    """If seeding drifts from the gate (someone re-keys `is_guest`), the guest
    persona silently degrades to anon and every cell where guest == anon goes
    VACUOUSLY green — 9 of the blind cells this file adds. This makes that
    degradation a hard failure instead of a quiet one."""
    client, _ = client_as(matrix_app, persona)
    if marker == "chat_form":
        assert client.get("/chat").status_code == 200
    else:
        assert MARKERS[marker] in client.get(url).text


def test_owner_repair_queue_comes_from_the_FIXTURE_not_this_machine(matrix_app, wiring):
    """The owner cell first failed on CI while passing locally, because the
    "Needs source" tab reads a ledger file that exists in this repo's data/ and
    not on a fresh checkout. Asserting the COUNT is exactly the fixture's one
    entry proves the patch took: if the real ledger ever leaks back in, this
    reads ~65 and fails here rather than diverging silently between machines."""
    client, _ = client_as(matrix_app, OWNER)
    body = client.get("/library").text
    assert 'href="/library?filter=needs-source"' in body
    assert "Needs source <b>1</b>" in body, "the repair queue is not the fixture's"


def test_guest_route_does_not_hijack_a_logged_in_session(matrix_app, wiring):
    """QA-2 bug: /guest overwrote session["taste"] with the owner's published
    snapshot and set is_guest — for ANYONE, including a logged-in pilot user. The
    victim then saw the owner's taste rendered as their own on /analytics,
    /explore and /artists until they next loaded /dashboard. Both personas still
    land on /dashboard; only the authenticated one keeps its own session."""
    from .app import _signer, _store
    client, sid = client_as(matrix_app, USER)
    before = dict(_store.get(sid)["taste"])
    r = client.get("/guest")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    served = _signer.unsign(r.cookies.get(config.SESSION_COOKIE)) or sid
    sess = _store.get(served)
    assert sess["taste"] == before, "an authed session's taste was overwritten"
    assert not sess.get("is_guest"), "a logged-in user was marked a guest"


def test_dead_lettered_tracks_reach_the_repair_queue(matrix_app, wiring):
    """A track the ORDINARY worker gives up on (failed at MAX_ATTEMPTS) never
    gets a re-extraction ledger entry, so before this it was blank, never
    retried, and INVISIBLE to /library?filter=needs-source — the one place the
    owner would look. Found live: "Fukk A Interview" was stuck exactly this way.
    The queue must be both populations, not just the ledger's."""
    from ..store.cache import JOB_FAILED, MAX_ATTEMPTS
    from ..store.models import ExtractionJob

    cache = wiring.cache
    cache.remember_meta([{"spotify_track_id": "deadltr1", "track_name": "Gave Up",
                          "artist_names": "Band"}])
    with cache._Session() as s:
        s.add(ExtractionJob(spotify_track_id="deadltr1", status=JOB_FAILED,
                            attempts=MAX_ATTEMPTS, last_error="no usable source"))
        s.commit()
    assert "deadltr1" in cache.dead_lettered_ids()

    client, _ = client_as(matrix_app, OWNER)
    body = client.get("/library?filter=needs-source").text
    assert "Gave Up" in body, "a dead-lettered track is missing from the repair queue"
    # ...and it is not confused with a track that still has work coming
    assert "deadltr2" not in cache.dead_lettered_ids()


def test_logging_in_clears_a_previous_demo_persona(matrix_app, wiring, monkeypatch):
    """Owner report: "when I click back it doesn't load my Spotify page, it just
    brings me to the demo."

    `is_guest` was STICKY. `_store.rotate()` preserves session data across the
    login rotation, so a visitor who had ever clicked "View as guest" stayed
    flagged a guest forever — demo banner on every page, and the owner's
    snapshot taste sitting in their session until /dashboard overwrote it. A
    real login must supersede the demo persona."""
    from spotipy.oauth2 import SpotifyPKCE

    from . import auth_web
    from .app import _signer, _store

    sid = _store.new()
    sess = _store.get(sid)
    sess["is_guest"] = True                       # they browsed the demo first
    sess["taste"] = {"range_ids": {"short_term": ["demo_track"]}}
    auth_web.build_authorize_url(sess)            # start a real login
    state = sess["pkce"]["state"]
    monkeypatch.setattr(SpotifyPKCE, "get_access_token", lambda self, code=None,
                        check_cache=True: self.cache_handler.save_token_to_cache(
                            {"access_token": "tok", "token_type": "Bearer",
                             "expires_in": 3600, "scope": config.SCOPES}) or "tok")

    client = TestClient(matrix_app, follow_redirects=False)
    client.cookies.set(config.SESSION_COOKIE, _signer.sign(sid))
    r = client.get(f"/callback?code=abc&state={state}")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"

    served = _signer.unsign(r.cookies.get(config.SESSION_COOKIE))
    after = _store.get(served)
    assert auth_web.is_authenticated(after), "the login itself must still work"
    assert not after.get("is_guest"), "a logged-in user was left flagged a guest"
    assert "taste" not in after, "the demo snapshot survived into a real session"


def test_library_payload_is_bounded_by_the_page_not_the_corpus(matrix_app, wiring):
    """P3, the growth gate. /library shipped every known track in one document —
    757 KB for 1,259 rows on the live corpus, projecting to ~3 MB at 5,000. This
    is the test that fails the day someone removes the slice."""
    from . import library as lib

    cache = wiring.cache
    n = lib.PAGE_SIZE * 3
    cache.remember_meta([{"spotify_track_id": f"pg{i:04d}", "track_name": f"Paged {i}",
                          "artist_names": "Band"} for i in range(n)])
    client, _ = client_as(matrix_app, ANON)
    body = client.get("/library").text
    # one <tr> per row plus the header row
    assert body.count("<tr") <= lib.PAGE_SIZE + 1, "the page is not bounded"
    # ...and the coverage claim still describes the WHOLE corpus, not the page.
    # Assert the invariant, not an exact total: the fixture seeds other tracks
    # too, and hard-coding a count would break on any future fixture change
    # while saying nothing about the honesty property being guarded.
    import re as _re
    text = _re.sub(r"<[^>]+>", "", body)          # the number is wrapped in <b>
    known = int(_re.search(r"of\s+([\d]+)\s+known", text).group(1))
    assert known >= n, f"the honesty line shrank to the page: {known}"
    assert 'class="pager"' in body


def test_paging_never_hides_a_track_from_the_last_page(matrix_app, wiring):
    """The pager must reach the tail, and a deep page must render real rows —
    the two ways a bounded page silently becomes a truncated corpus."""
    from . import library as lib

    cache = wiring.cache
    n = lib.PAGE_SIZE * 3
    cache.remember_meta([{"spotify_track_id": f"zz{i:04d}", "track_name": f"Zed {i:04d}",
                          "artist_names": "Band"} for i in range(n)])
    client, _ = client_as(matrix_app, ANON)
    first = client.get("/library").text
    assert "page=3" in first or "page=4" in first, "the last page is unreachable"
    deep = client.get("/library?page=3")
    assert deep.status_code == 200 and deep.text.count("<tr") > 1
    # a search still spans everything, from page 1
    hit = client.get("/library?q=Zed+0299").text
    assert "Zed 0299" in hit


# The Cloudflare H5 fallback Worker replaces ANY origin response with these
# statuses by its "Demo offline — by design" card (infra/cloudflare/
# origin-fallback-worker.js, ORIGIN_DOWN). An app that returns one is not
# showing its own error page — it is telling every visitor the site is down.
_ORIGIN_DOWN = {502, 504, 521, 522, 523, 530}


def _throttled(*a, **k):
    from spotipy.exceptions import SpotifyException
    raise SpotifyException(429, -1, "rate/request limit")


def test_a_spotify_rate_limit_does_not_masquerade_as_the_site_being_down(
        matrix_app, wiring, monkeypatch):
    """THE bug: logging in returned 502 when Spotify throttled the dashboard
    fetch, so Cloudflare's fallback replaced it with "Demo offline — by design".
    The app was healthy; the visitor was told the whole site was gone.

    503 says "temporarily unavailable" and passes through as OUR page."""
    monkeypatch.setattr("src.webapp.app.fetch_top_tracks", _throttled)
    client, sid = client_as(matrix_app, USER)
    r = client.get("/dashboard")
    assert r.status_code not in _ORIGIN_DOWN, (
        f"{r.status_code} is in the fallback Worker's origin-down set — "
        "Cloudflare will replace this page with the offline card")
    assert r.status_code == 503 and r.headers.get("Retry-After")
    assert "rate-limiting" in r.text and "still logged in" in r.text


def test_a_rate_limit_does_not_log_the_visitor_out(matrix_app, wiring, monkeypatch):
    """Recovering from a transient upstream error meant logging in AGAIN — more
    API calls, deeper into the same rate limit. The session must survive."""
    from . import auth_web
    from .app import _store

    monkeypatch.setattr("src.webapp.app.fetch_top_tracks", _throttled)
    client, sid = client_as(matrix_app, USER)
    client.get("/dashboard")
    assert _store.get(sid) is not None, "the session was destroyed"
    assert auth_web.is_authenticated(_store.get(sid))


def test_an_expired_token_still_drops_the_session(matrix_app, wiring, monkeypatch):
    """The inverse: when the TOKEN is the problem the session genuinely cannot
    be recovered, so it must still be dropped rather than looping forever."""
    from . import auth_web as auth_web_mod
    from .app import _store

    def _bad_token(*a, **k):
        raise auth_web_mod.AuthError("Not authenticated.")
    monkeypatch.setattr("src.webapp.app.auth_web.client_from_session", _bad_token)
    client, sid = client_as(matrix_app, USER)
    r = client.get("/dashboard")
    assert r.status_code == 401 and r.status_code not in _ORIGIN_DOWN
    assert _store.get(sid) is None, "an unusable session was kept"


def test_no_route_returns_a_status_the_fallback_treats_as_death(matrix_app, wiring):
    """Standing tripwire across the whole matrix. Any 502/504/521-523/530 gets
    swallowed by Cloudflare and rendered as "the site is offline", so it can
    never be a legitimate answer from this app."""
    for row in MATRIX:
        for persona in PERSONAS:
            client, _ = client_as(matrix_app, persona)
            kwargs: dict[str, Any] = {}
            if row.data:
                kwargs["data"] = row.data
            if row.files:
                kwargs["files"] = row.files
            resp = client.request(row.method, row.url, **kwargs)
            assert resp.status_code not in _ORIGIN_DOWN, (
                f"{row.method} {row.url} as {persona} returned "
                f"{resp.status_code} — the fallback Worker would hide it")


def test_owner_gate_fails_closed_without_env(matrix_app, wiring, monkeypatch):
    """The control that FLIPS. If someone stubs the owner gate open to "simplify
    the fixture", every OWNER cell still passes — but this one must fail. It
    also re-proves D-56's fail-closed posture at the route layer."""
    monkeypatch.delenv("WEBAPP_OWNER_SPOTIFY_ID", raising=False)
    client, _ = client_as(matrix_app, OWNER)
    assert MARKERS["repair_link_form"] not in client.get(f"/song/{TRACK}").text
    assert MARKERS["needs_source_tab"] not in client.get("/library").text
    assert client.get(f"/audio/{TRACK}").status_code == 303
    client.post(f"/song/{TRACK}/repair-link", data={"url": "https://youtu.be/x"})
    assert REPAIR not in wiring.fired, "the repair engine ran with the gate closed"


_ORACLE = [r for r in MATRIX
           if "{track_id}" in r.path and not r.skip_oracle]


@pytest.mark.parametrize("persona", [ANON, GUEST, USER])
@pytest.mark.parametrize("row", _ORACLE, ids=[f"{r.method} {r.path}" for r in _ORACLE])
def test_gate_runs_before_existence_no_oracle(matrix_app, wiring, row, persona):
    """The /spectrogram lesson generalised: a non-privileged caller must get the
    SAME answer for a track that exists and one that does not, or the status code
    is an existence oracle over the corpus."""
    client, _ = client_as(matrix_app, persona)
    kwargs: dict[str, Any] = {}
    if row.data:
        kwargs["data"] = row.data
    if row.files:
        kwargs["files"] = row.files
    a = client.request(row.method, row.url, **kwargs)
    b = client.request(row.method, row.url.replace(TRACK, "nope9"), **kwargs)
    norm = lambda r, t: (r.status_code,  # noqa: E731
                         r.headers.get("location", "").replace(t, "X"))
    assert norm(a, TRACK) == norm(b, "nope9"), (
        f"{row.method} {row.path} as {persona}: existing and missing tracks "
        "answer differently — an enumeration oracle")
