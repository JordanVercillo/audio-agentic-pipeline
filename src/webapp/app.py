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
from .analytics import (
    acoustic_signature,
    cluster_color,
    cluster_composition,
    popularity_context,
    scatter_svg,
)
from .archetype import derive_archetype
from .explore import (
    catalog_groups,
    histogram_svg,
    load_catalog,
    load_stats,
    percentile_of,
    scatter_xy_svg,
    window_strip,
)
from .featurestore import FeatureStore
from .rag import TasteRAG
from .recommend import (
    parse_constraints,
    popularity_stats,
    recommend,
    seed_targets,
    stats_from_frame,
)
from .sessions import CookieSigner, SessionStore
from .taste import (
    absolute_profile,
    drift_over_rows,
    loudness_svg,
    radar_svg,
    sections_svg,
    track_summary,
)

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

# Rough per-track extraction cost (yt-dlp download + librosa DSP + spectrogram),
# for the progress ETA. Measured ~50 s/track on the owner PC; shown as an
# estimate only, never a promise. Worker processes the queue serially.
_SECONDS_PER_TRACK = 50


def ingestion_status(range_ids: dict[str, list[str]], cache: FeatureCache) -> dict[str, Any]:
    """Live ingestion progress for a visitor's tracks — CACHE-ONLY (no Spotify
    call), so the dashboard can poll it cheaply every few seconds (serves the
    efficiency goal: polling must not re-hit the API). Pure + testable."""
    all_ids = list({t for ids in (range_ids or {}).values() for t in ids})
    if not all_ids:
        return {"total": 0, "analyzed": 0, "analyzing": 0, "queued": 0,
                "running": 0, "failed": 0, "current": None, "eta_seconds": 0, "done": True}
    st = cache.job_status(all_ids)
    running = cache.running_ids(all_ids)
    current = None
    if running:
        m = cache.get_meta(running[0]) or {}
        current = {"name": m.get("track_name") or "", "artist": m.get("artist_names") or ""}
    analyzing = st["queued"] + st["running"]
    return {
        "total": st["total"], "analyzed": st["cached"], "analyzing": analyzing,
        "queued": st["queued"], "running": st["running"], "failed": st["failed"],
        "current": current, "eta_seconds": analyzing * _SECONDS_PER_TRACK,
        "done": analyzing == 0,
    }


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
                    {"spotify_track_id": tid, "track_name": name, "artist_names": artist,
                     "popularity": r.get("popularity")})
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

    # Registered after (= wraps) the session middleware: www visitors are
    # bounced to the apex BEFORE any cookie work — session cookies are
    # host-scoped, so a www login would otherwise strand the session.
    @app.middleware("http")
    async def www_redirect(request: Request, call_next):
        # Allowlisted: ONLY www.<our apex> redirects. Matching any "www.*" Host
        # would let a spoofed Host header mint a 301 to an attacker's domain.
        host = request.headers.get("host", "").split(":")[0].lower()
        if host == f"www.{config.CANONICAL_HOST}":
            return RedirectResponse(
                str(request.url.replace(netloc=config.CANONICAL_HOST)),
                status_code=301)
        return await call_next(request)

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

    @app.get("/status")
    def status(request: Request):
        """Live ingestion progress (JSON) — the dashboard polls this while songs
        analyze. Cache-only: no Spotify call, so polling is cheap."""
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return {"authed": False, "done": True}
        range_ids = (session.get("taste") or {}).get("range_ids") or {}
        return {"authed": True, **ingestion_status(range_ids, _feature_cache())}

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

        # Taste vs popularity (slice P) — fetched context, absent-safe: renders
        # only when enough popularity values have been seen (the field is
        # deprecated upstream and may be missing entirely).
        pops = cache.all_popularity()
        ctx["popularity"] = popularity_context(
            [pops[t] for t in set(all_ids) if t in pops], list(pops.values()))

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
        taste["popularity"] = (ctx.get("popularity") or {}).get("line")
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

    def _explore_context(session: dict[str, Any], f: str, x: str, y: str,
                         ) -> Optional[dict[str, Any]]:
        """The /explore view: marts + the visitor's overlay. None = no dashboard yet."""
        taste = session.get("taste") or {}
        range_ids: dict[str, list[str]] = taste.get("range_ids") or {}
        if not range_ids:
            return None

        catalog = load_catalog()
        stats = load_stats()
        if catalog is None or stats is None:
            return {"authed": True, "built": False}

        cols = list(catalog["column"])
        f = f if f in cols else ("danceability" if "danceability" in cols else cols[0])
        x = x if x in cols else "tempo"
        y = y if y in cols else "energy"

        cache = _feature_cache()
        perceptual = cache.all_perceptual()
        user_ids = [t for ids in range_ids.values() for t in ids]
        user_set = set(user_ids)

        population = [p[f] for p in perceptual.values()
                      if isinstance(p.get(f), (int, float))]
        user_vals = [perceptual[t][f] for t in dict.fromkeys(user_ids)
                     if t in perceptual and isinstance(perceptual[t].get(f), (int, float))]

        spec = catalog[catalog["column"] == f].iloc[0].to_dict()
        srow = stats.loc[f]
        chip = None
        if user_vals:
            med = sorted(user_vals)[len(user_vals) // 2]
            chip = {"pct": percentile_of(med, population),
                    "n": len(user_vals),
                    "median": round(med, 2 if abs(med) < 10 else 0)}

        per_window = {w: [perceptual[t][f] for t in ids
                          if t in perceptual and isinstance(perceptual[t].get(f), (int, float))]
                      for w, ids in range_ids.items()}

        model = cl.latest_model(cache, "song")
        assigned = cl.track_assignments(cache, model.id) if model else {}
        meta = cache.all_meta()
        points = [{"id": tid, "x": p.get(x), "y": p.get(y),
                   "cluster_id": (assigned.get(tid) or {}).get("cluster_id"),
                   "name": (meta.get(tid) or {}).get("track_name", tid)}
                  for tid, p in perceptual.items()]

        return {
            "authed": True, "built": True,
            "groups": catalog_groups(catalog),
            "f": f, "x": x, "y": y, "spec": spec,
            "stat": {"n": int(srow["n"]), "p50": srow["p50"],
                     "min": srow["min"], "max": srow["max"]},
            "hist": histogram_svg(srow, user_vals),
            "chip": chip,
            "strip": window_strip(per_window, spec.get("unit", "")),
            "scatter": scatter_xy_svg(points, user_set,
                                      x_label=str(catalog.set_index("column").loc[x, "friendly"]),
                                      y_label=str(catalog.set_index("column").loc[y, "friendly"])),
            "columns": [{"column": c["column"], "friendly": c["friendly"]}
                        for c in catalog.to_dict("records")],
        }

    def _recommend_context(session: dict[str, Any],
                           params: dict[str, str]) -> Optional[dict[str, Any]]:
        """The /recommend view (Epic G): the retired API's tunables over OUR
        features. None = no dashboard yet; built=False = marts not built."""
        taste = session.get("taste") or {}
        if not (taste.get("range_ids") or {}):
            return None
        catalog = load_catalog()
        stats_df = load_stats()
        if catalog is None or stats_df is None:
            return {"authed": True, "built": False}

        cache = _feature_cache()
        perceptual = cache.all_perceptual()
        pops = cache.all_popularity()
        meta = cache.all_meta()
        allowed = set(catalog["column"]) | {"popularity"}

        # popularity joins each row as a constraint axis (fetched context)
        rows = {tid: ({**p, "popularity": float(pops[tid])} if tid in pops else dict(p))
                for tid, p in perceptual.items()}

        seed = params.get("seed") or ""
        if seed not in perceptual:
            seed = ""
        constraints = parse_constraints(params, allowed)
        if seed and not any(c.kind == "target" for c in constraints):
            # "more like this": the seed's own values become VISIBLE targets
            constraints = constraints + seed_targets(
                perceptual[seed], allowed, pops.get(seed))

        stats = stats_from_frame(stats_df)
        pstats = popularity_stats(pops)
        if pstats:
            stats["popularity"] = pstats

        ranked = recommend(rows, constraints, stats,
                           exclude={seed} if seed else set(), limit=20)

        model = cl.latest_model(cache, "song")
        assigned = cl.track_assignments(cache, model.id) if model else {}
        results = []
        for r in ranked:
            m = meta.get(r["id"]) or {}
            cid = (assigned.get(r["id"]) or {}).get("cluster_id")
            results.append({
                **r, "name": m.get("track_name") or r["id"],
                "artist": m.get("artist_names") or "",
                "color": cluster_color(int(cid)) if cid is not None else None,
                "chips": [(c, round(r["values"][c], 2)) for c in sorted(r["values"])],
            })

        form = {f"{c.kind}_{c.column}": c.value for c in constraints}
        seed_options = sorted(
            ({"id": t, "name": (meta.get(t) or {}).get("track_name") or t}
             for t in perceptual),
            key=lambda o: o["name"].lower())
        feature_rows = catalog[["column", "friendly", "tier", "unit"]].to_dict("records")
        feature_rows.append({"column": "popularity", "friendly": "Popularity",
                             "tier": "fetched", "unit": "0–100"})
        return {"authed": True, "built": True, "seed": seed,
                "seed_name": (meta.get(seed) or {}).get("track_name") if seed else None,
                "form": form, "features": feature_rows,
                "seed_options": seed_options, "results": results,
                "active": bool(constraints)}

    @app.get("/recommend", response_class=HTMLResponse)
    def recommend_view(request: Request):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        ctx = _recommend_context(session, dict(request.query_params))
        if ctx is None:
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(request, "recommend.html", ctx)

    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, f: str = "danceability",
                x: str = "tempo", y: str = "energy"):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        ctx = _explore_context(session, f, x, y)
        if ctx is None:
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(request, "explore.html", ctx)

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
            ctx["loudness"] = loudness_svg(
                cache.loudness_curve(track_id),
                beat_times=cache.beat_times(track_id),
                duration_sec=features.get("duration_sec"),
                meter=cache.time_signature(track_id) or 4)
            ctx["sections"] = sections_svg(
                cache.sections(track_id), features.get("duration_sec"))
            ctx["has_spectrogram"] = _spectrogram_path(track_id).exists()
            ctx["similar"] = [
                {"id": sid, "name": (cache.get_meta(sid) or {}).get("track_name") or sid,
                 "artist": (cache.get_meta(sid) or {}).get("artist_names") or ""}
                for sid, _dist in cache.similar(track_id, k=6)
            ]
        return templates.TemplateResponse(request, "song.html", ctx)

    @app.get("/spectrogram/{track_id}")
    def spectrogram(request: Request, track_id: str):
        # Auth-gate BEFORE the existence check so an unauthenticated caller can't
        # use 200-vs-404 as an analyzed-track enumeration oracle. The <img> on
        # /song sends the session cookie, so legit rendering is unaffected.
        if not auth_web.is_authenticated(request.state.session):
            return RedirectResponse("/", status_code=303)
        path = _spectrogram_path(track_id)
        if not path.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="no spectrogram")
        return FileResponse(path, media_type="image/png")

    @app.post("/logout")
    def logout(request: Request):
        # POST-only: a GET link could be triggered cross-site (<img src=/logout>)
        # to force-logout visitors — nuisance CSRF, closed by requiring a form.
        _store.delete(request.state.sid)
        request.state.sid = _store.new()
        return RedirectResponse("/", status_code=303)

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return templates.TemplateResponse(request, "privacy.html", {
            "authed": auth_web.is_authenticated(request.state.session),
            "ttl_minutes": config.SESSION_TTL_SECONDS // 60,
        })

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
