"""
app.py — FastAPI application for the P8 production pilot (SPEC P8, D-7).

Routes:
    GET /            landing page (Log in with Spotify)
    GET /login       start session-scoped PKCE → redirect to Spotify
    GET /callback    verify state (CSRF) → swap code for token → /dashboard
    GET /dashboard   the visitor's top tracks + acoustic overlap insight
    GET /logout      drop the session
    GET /healthz     liveness (Cloud Run)

Sessions are server-side (see sessions.py): the browser holds only a signed
session-id cookie; the access token stays on the server and expires (D-7).
No Spotify secret anywhere (D-8).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..ingestion.fetchers import fetch_top_tracks
from . import auth_web, config
from .featurestore import FeatureStore
from .sessions import CookieSigner, SessionStore

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))

_store = SessionStore(ttl_seconds=config.SESSION_TTL_SECONDS)
_signer = CookieSigner(config.get_session_secret())
_SECURE_COOKIE = config.REDIRECT_URI.startswith("https://")

_TIME_RANGES = [
    ("short_term", "Last 4 weeks"),
    ("medium_term", "Last 6 months"),
    ("long_term", "All time"),
]


@lru_cache(maxsize=1)
def _feature_store() -> Optional[FeatureStore]:
    """The gold acoustic corpus, loaded once. None if the warehouse isn't built."""
    try:
        return FeatureStore(config.MODELED_DIR)
    except FileNotFoundError as exc:
        logger.warning("Feature store unavailable (%s) — overlap insight disabled.", exc)
        return None


def build_dashboard_context(client: Any, store: Optional[FeatureStore]) -> dict[str, Any]:
    """
    Fetch the visitor's top tracks (3 ranges) and join against the corpus.

    Pure w.r.t. I/O boundaries: `client` supplies the tracks (mockable in tests),
    `store` supplies the corpus. Returns the template context.
    """
    ranges: list[dict[str, Any]] = []
    all_ids: list[str] = []
    for key, label in _TIME_RANGES:
        df = fetch_top_tracks(time_range=key, limit=20, sp=client)
        tracks = []
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                tid = r["spotify_track_id"]
                all_ids.append(tid)
                tracks.append({
                    "rank": int(r.get("rank", 0)),
                    "name": r.get("track_name", ""),
                    "artist": r.get("artist_names", ""),
                    "id": tid,
                })
        ranges.append({"key": key, "label": label, "tracks": tracks})

    profile = store.profile(all_ids) if store is not None else None
    overlap = set(profile["overlap_ids"]) if profile else set()
    for rng in ranges:
        for t in rng["tracks"]:
            t["in_corpus"] = t["id"] in overlap

    return {"ranges": ranges, "profile": profile, "track_total": len(set(all_ids))}


def create_app() -> FastAPI:
    app = FastAPI(title="Vercillo Analytics — Taste Pilot", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")

    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        sid = _signer.unsign(request.cookies.get(config.SESSION_COOKIE))
        session = _store.get(sid)
        if session is None:
            sid = _store.new()
            session = _store.get(sid)
        request.state.sid = sid
        request.state.session = session
        response = await call_next(request)
        # request.state.sid may have been rotated by a route (login).
        response.set_cookie(
            config.SESSION_COOKIE, _signer.sign(request.state.sid),
            httponly=True, samesite="lax", secure=_SECURE_COOKIE,
            max_age=config.SESSION_TTL_SECONDS,
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        authed = auth_web.is_authenticated(request.state.session)
        return templates.TemplateResponse(request, "index.html", {"authed": authed})

    @app.get("/login")
    def login(request: Request):
        url = auth_web.build_authorize_url(request.state.session)
        return RedirectResponse(url, status_code=307)

    @app.get("/callback", response_class=HTMLResponse)
    def callback(request: Request, code: Optional[str] = None,
                 state: Optional[str] = None, error: Optional[str] = None):
        if error:
            return templates.TemplateResponse(
                request, "error.html",
                {"detail": f"Spotify denied access: {error}", "authed": False},
                status_code=400)
        try:
            auth_web.exchange_code(request.state.session, code or "", state)
        except auth_web.AuthError as exc:
            return templates.TemplateResponse(
                request, "error.html", {"detail": str(exc), "authed": False},
                status_code=400)
        # Session-fixation defense: fresh id now that we're authenticated.
        request.state.sid = _store.rotate(request.state.sid)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        try:
            client = auth_web.client_from_session(session)
            ctx = build_dashboard_context(client, _feature_store())
        except Exception as exc:  # noqa: BLE001 — show a clean error, drop the session
            logger.exception("dashboard build failed")
            _store.delete(request.state.sid)
            request.state.sid = _store.new()
            return templates.TemplateResponse(
                request, "error.html",
                {"detail": f"Could not load your data: {exc}", "authed": False},
                status_code=502)
        return templates.TemplateResponse(request, "dashboard.html", {**ctx, "authed": True})

    @app.get("/logout")
    def logout(request: Request):
        _store.delete(request.state.sid)
        request.state.sid = _store.new()
        return RedirectResponse("/", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
