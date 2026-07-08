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

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..ingestion.fetchers import fetch_top_artists, fetch_top_tracks
from ..store import clusters as cl
from ..store.cache import FeatureCache
from . import auth_web, config
from .analytics import acoustic_signature, cluster_color, cluster_composition, scatter_svg
from .archetype import derive_archetype
from .featurestore import FeatureStore
from .rag import TasteRAG
from .sessions import CookieSigner, SessionStore
from .taste import absolute_profile, drift_over_rows, radar_svg, track_summary

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))

# Where the extraction worker / seed write mel-spectrogram PNGs (GCS in prod).
_SPECTROGRAM_DIR = _BASE.parent.parent / "data" / "spectrograms"


def _spectrogram_path(track_id: str) -> Path:
    return _SPECTROGRAM_DIR / f"{Path(track_id).name}.png"  # .name strips path traversal

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
    """The gold corpus — used only for the RAG feature glossary now. None if unbuilt."""
    try:
        return FeatureStore(config.MODELED_DIR)
    except FileNotFoundError as exc:
        logger.warning("Feature store unavailable (%s) — RAG glossary disabled.", exc)
        return None


@lru_cache(maxsize=1)
def _feature_cache() -> FeatureCache:
    """The shared, track-keyed feature cache (Epic A) — the dashboard's feature source."""
    return FeatureCache()


def build_dashboard_context(client: Any, cache: FeatureCache) -> dict[str, Any]:
    """
    Fetch the visitor's top tracks (3 ranges) and describe their OWN analyzed
    songs from the shared cache: hits render real acoustic features now, misses
    are queued for background extraction (analyze once, ever — D-11).

    `client` supplies the tracks and `cache` the features — both mockable in tests.
    """
    ranges: list[dict[str, Any]] = []
    all_ids: list[str] = []
    per_range_ids: dict[str, list[str]] = {}
    meta_items: list[dict[str, Any]] = []
    for key, label in _TIME_RANGES:
        df = fetch_top_tracks(time_range=key, limit=20, sp=client)
        tracks, ids_here = [], []
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                tid = r["spotify_track_id"]
                name, artist = r.get("track_name", ""), r.get("artist_names", "")
                all_ids.append(tid)
                ids_here.append(tid)
                meta_items.append(
                    {"spotify_track_id": tid, "track_name": name, "artist_names": artist})
                tracks.append({"rank": int(r.get("rank", 0)), "name": name,
                               "artist": artist, "id": tid, "art": r.get("album_image_url")})
        per_range_ids[key] = ids_here
        ranges.append({"key": key, "label": label, "tracks": tracks})

    # The shared cache: remember metadata (for the worker's search), read hits,
    # queue misses for extraction, report coverage.
    cache.remember_meta(meta_items)
    cached = cache.get(all_ids)          # {id: features} — the visitor's OWN analyzed songs
    cache.enqueue(all_ids)               # misses → extraction queue (idempotent)
    coverage = cache.job_status(all_ids)

    analyzed = set(cached)
    for rng in ranges:
        for t in rng["tracks"]:
            t["analyzed"] = t["id"] in analyzed
            t["feat"] = track_summary(cached.get(t["id"]))  # hover tooltip

    rows = list(cached.values())
    per_range_rows = {k: [cached[i] for i in ids if i in cached]
                      for k, ids in per_range_ids.items()}
    return {
        "ranges": ranges,
        "range_ids": per_range_ids,
        "profile": absolute_profile(rows),
        "drift": drift_over_rows(per_range_rows),
        "artists": _top_artists(client),
        "coverage": {"analyzed": coverage["cached"], "total": coverage["total"],
                     "analyzing": coverage["queued"] + coverage["running"]},
        "track_total": len(set(all_ids)),
    }


def _top_artists(client: Any, limit: int = 12) -> list[dict[str, Any]]:
    """The visitor's top artists (with Spotify genres — which tracks don't expose)."""
    try:
        df = fetch_top_artists(time_range="medium_term", limit=limit, sp=client)
    except Exception:  # noqa: BLE001 — a nice-to-have section, never fatal
        return []
    if df is None or df.empty:
        return []
    return [
        {
            "name": r.get("artist_name", ""),
            "genres": r.get("genres", ""),
            "image": r.get("image_url"),
        }
        for _, r in df.head(limit).iterrows()
    ]


def _slim_taste(ctx: dict[str, Any]) -> dict[str, Any]:
    """The grounding-relevant subset of the dashboard context, cached in-session for /ask."""
    return {
        "profile": ctx.get("profile"),
        "drift": ctx.get("drift"),
        "coverage": ctx.get("coverage"),
        "range_ids": ctx.get("range_ids"),  # for /analytics
        "artists": [{"name": a["name"], "genres": a.get("genres", "")}
                    for a in (ctx.get("artists") or [])],
        "ranges": [
            {"label": r["label"],
             "tracks": [{"name": t["name"], "artist": t["artist"],
                         "analyzed": t.get("analyzed", False)}
                        for t in r["tracks"][:10]]}
            for r in ctx.get("ranges", [])
        ],
    }


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
            ctx = build_dashboard_context(client, _feature_cache())
        except Exception as exc:  # noqa: BLE001 — show a clean error, drop the session
            logger.exception("dashboard build failed")
            _store.delete(request.state.sid)
            request.state.sid = _store.new()
            return templates.TemplateResponse(
                request, "error.html",
                {"detail": f"Could not load your data: {exc}", "authed": False},
                status_code=502)
        session["taste"] = _slim_taste(ctx)  # compact grounding for /ask
        return templates.TemplateResponse(request, "dashboard.html", {**ctx, "authed": True})

    @app.post("/ask", response_class=HTMLResponse)
    def ask(request: Request, q: str = Form("")):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        taste = session.get("taste")
        if not taste:  # dashboard hasn't been loaded this session
            return RedirectResponse("/dashboard", status_code=303)
        question = (q or "").strip()
        if not question:
            return RedirectResponse("/dashboard", status_code=303)
        result = TasteRAG(_feature_store()).answer(question, taste)
        return templates.TemplateResponse(request, "ask.html", {
            "authed": True, "question": question,
            "answer": result["answer"], "source": result["source"],
        })

    def _analytics_context(session: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Build the analytics view context AND enrich the in-session taste with
        signature/clusters/archetype so /ask and /classify ground on them (Epic D).
        Returns None when the dashboard hasn't been visited yet."""
        taste = session.get("taste") or {}
        range_ids: dict[str, list[str]] = taste.get("range_ids") or {}
        if not range_ids:
            return None

        cache = _feature_cache()
        all_ids = [t for ids in range_ids.values() for t in ids]
        cached = cache.get(all_ids)

        ctx: dict[str, Any] = {"authed": True, "trained": False, "archetype": None,
                               "coverage": taste.get("coverage"),
                               "drift": taste.get("drift")}
        # Signature works even before any model is trained (population stats only).
        population = list(cache.all_features().values())
        ctx["signature"] = acoustic_signature(list(cached.values()), population)

        model = cl.latest_model(cache, "song")
        if model is not None:
            ctx["trained"] = True
            assigned = cl.track_assignments(cache, model.id)
            for tid, feats in cached.items():  # online-assign cache hits the model missed
                if tid not in assigned:
                    cid = cl.assign_track(cache, model, tid, feats)
                    if cid is not None:
                        assigned[tid] = {"cluster_id": cid, "map_x": None, "map_y": None}

            labels: dict[str, str] = model.labels
            per_window = {w: [assigned[t]["cluster_id"] for t in ids if t in assigned]
                          for w, ids in range_ids.items()}
            ctx["composition"] = cluster_composition(per_window, labels)
            ctx["legend"] = [{"cluster_id": int(c), "label": lbl,
                              "color": cluster_color(int(c))}
                             for c, lbl in sorted(labels.items(), key=lambda kv: int(kv[0]))]

            arch = derive_archetype(per_window, labels, taste.get("drift"),
                                    ctx["signature"])
            if arch:
                arch["color"] = cluster_color(arch["home_color_id"])
                ctx["archetype"] = arch

            meta = cache.all_meta()
            population_pts = [{"id": t, "x": a["map_x"], "y": a["map_y"],
                               "cluster_id": a["cluster_id"]}
                              for t, a in assigned.items()]
            user_pts = [{**p, "name": (meta.get(p["id"]) or {}).get("track_name", ""),
                         "artist": (meta.get(p["id"]) or {}).get("artist_names", "")}
                        for p in population_pts if p["id"] in cached]
            ctx["cluster_map"] = scatter_svg(population_pts, user_pts)

        artist_model = cl.latest_model(cache, "artist")
        if artist_model is not None:
            user_artists = {a["name"] for a in (taste.get("artists") or [])}
            buckets = cl.artist_buckets(cache, artist_model.id)
            ctx["artist_buckets"] = [
                {"label": artist_model.labels.get(str(cid), f"Cluster {cid}"),
                 "color": cluster_color(cid),
                 "artists": [{**a, "mine": a["artist"] in user_artists}
                             for a in members[:10]]}
                for cid, members in sorted(buckets.items())
            ]

        # Enrich the session taste — /ask and /classify ground on these (Epic D).
        taste["signature"] = ctx["signature"]
        taste["archetype"] = ctx["archetype"]
        comp = ctx.get("composition") or {}
        taste["clusters"] = {
            "windows": {w: [{"label": s["label"], "share": s["share"]} for s in segs]
                        for w, segs in (comp.get("windows") or {}).items()},
            "movement": comp.get("movement"),
        }
        session["taste"] = taste
        return ctx

    @app.get("/analytics", response_class=HTMLResponse)
    def analytics(request: Request):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        ctx = _analytics_context(session)
        if ctx is None:
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(request, "analytics.html", ctx)

    @app.post("/classify", response_class=HTMLResponse)
    def classify(request: Request):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        ctx = _analytics_context(session)  # refresh + enrich the grounding
        if ctx is None:
            return RedirectResponse("/dashboard", status_code=303)
        if not ctx.get("archetype"):
            return RedirectResponse("/analytics", status_code=303)
        result = TasteRAG(_feature_store()).classify(session["taste"])
        return templates.TemplateResponse(request, "profile.html", {
            "authed": True, "archetype": ctx["archetype"],
            "narrative": result["narrative"], "source": result["source"],
        })

    @app.get("/song/{track_id}", response_class=HTMLResponse)
    def song(request: Request, track_id: str):
        if not auth_web.is_authenticated(request.state.session):
            return RedirectResponse("/", status_code=303)
        cache = _feature_cache()
        features = cache.get([track_id]).get(track_id)
        meta = cache.get_meta(track_id) or {}
        ctx: dict[str, Any] = {
            "authed": True, "track_id": track_id,
            "name": meta.get("track_name") or track_id,
            "artist": meta.get("artist_names") or "",
            "analyzed": features is not None,
        }
        if features is not None:
            ctx["summary"] = track_summary(features)
            ctx["radar"] = radar_svg(features)
            ctx["has_spectrogram"] = _spectrogram_path(track_id).exists()
            ctx["similar"] = [
                {"id": sid, "name": (cache.get_meta(sid) or {}).get("track_name") or sid,
                 "artist": (cache.get_meta(sid) or {}).get("artist_names") or ""}
                for sid, _dist in cache.similar(track_id, k=6)
            ]
        return templates.TemplateResponse(request, "song.html", ctx)

    @app.get("/spectrogram/{track_id}")
    def spectrogram(track_id: str):
        path = _spectrogram_path(track_id)
        if not path.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="no spectrogram")
        return FileResponse(path, media_type="image/png")

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
