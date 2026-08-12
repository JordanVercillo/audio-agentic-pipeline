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

import json
import logging
import pathlib
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..dsp.feature_doc import RAW_FEATURE_PROMOTED
from ..ingestion.fetchers import (
    fetch_artist_top_tracks,
    fetch_top_artists,
    fetch_top_tracks,
    fetch_user_playlists,
    fetch_user_profile,
    iter_playlist_track_pages,
)
from ..store import clusters as cl
from ..store.cache import _SIMILARITY_COLS, FeatureCache
from ..store.dedup import canonicalize_ids, canonicalize_range_ids
from . import artists as artists_view_mod
from . import auth_web, config
from . import explore as explore_mod
from . import library as library_view_mod
from . import playlists as playlists_mod
from .analytics import (
    _SIGNATURE_DIMS,
    acoustic_signature,
    average_loudness_arc,
    cluster_color,
    cluster_composition,
    loudness_arc_svg,
    popularity_context,
    scatter_svg,
)
from .archetype import archetype_taxonomy, derive_archetype
from .artists import (
    artist_rollup,
    comparison_svg,
    corpus_artist_index,
    genre_strip,
    nearest_artists,
    your_top_by_artist,
)
from .explore import (
    catalog_groups,
    histogram_svg,
    load_catalog,
    load_raw_feature_dictionary,
    load_raw_feature_stats,
    load_stats,
    percentile_of,
    scatter_xy_svg,
    window_strip,
)
from .features_view import build_feature_detail
from .featurestore import FeatureStore
from .prompt_contract import PROMPT_VERSION
from .rag import TasteRAG
from .recommend import (
    apply_seed_targets,
    parse_constraints,
    popularity_stats,
    recommend,
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


_DEMO_PROFILE_PATH = _BASE.parent.parent / "data" / "demo_profile.json"

# D-56: the runner's ledger (read-only here — the runner is its single writer)
# and a repair-scratch dir SEPARATE from the runner's (no file collisions).
_LEDGER_PATH = _BASE.parent.parent / "data" / "re_extract_ledger.json"
_REPAIR_AUDIO_DIR = _BASE.parent.parent / "data" / "tmp_repair"
# V2: RETAINED owner uploads — the only copy of tracks with no external source.
_OWNER_AUDIO_DIR = _BASE.parent.parent / "data" / "owner_audio"
# A repair mutates the corpus, so it rebuilds the derived planes (explore.py's
# _MARTS is the same dir) — otherwise /explore + the chat keep the old numbers.
_MARTS_DIR = _BASE.parent.parent / "data" / "marts"
_UPLOAD_FILE = File(...)  # module-level singleton (B008 — the FastAPI idiom)


def load_demo_profile() -> Optional[dict[str, Any]]:
    """The owner's saved taste snapshot for guest/demo mode (H7, D-30), or None.

    Written by `scripts/snapshot_demo_profile.py` from the gold warehouse; lets
    "View as guest" render the full personalized analytics with no live token.
    """
    try:
        prof = json.loads(_DEMO_PROFILE_PATH.read_text())
    except (OSError, ValueError):
        return None
    return prof if isinstance(prof, dict) and prof.get("range_ids") else None

_store = SessionStore(ttl_seconds=config.SESSION_TTL_SECONDS)
_signer = CookieSigner(config.get_session_secret())
_SECURE_COOKIE = config.REDIRECT_URI.startswith("https://")

_TIME_RANGES = [
    ("short_term", "Last 4 weeks"),
    ("medium_term", "Last 6 months"),
    ("long_term", "All time"),
]

# How deep each top-tracks range is fetched (D-34; Spotify max 50). THE single
# source for the number — the My-Library "why only N analyzed" explainer derives
# from it, so retuning the depth can't make the UI lie. Was 20 (3×20 with
# overlap ≈ 39 unique — the owner's "why 39 songs" mystery).
_TOP_LIMIT = 50

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


def _load_mart(name: str):
    """A mart as a DataFrame, or None. mtime-keyed so a rebuild is picked up
    without restarting the app."""
    path = _MARTS_DIR / f"{name}.parquet"
    try:
        return _load_mart_cached(str(path), path.stat().st_mtime)
    except (OSError, FileNotFoundError):
        return None


@lru_cache(maxsize=8)
def _load_mart_cached(path: str, _mtime: float):
    try:
        import pandas as pd
        return pd.read_parquet(path)
    except Exception:  # noqa: BLE001 - a missing mart must not 500 the site
        return None


def _render_explainer() -> Optional[str]:
    """docs/HOW_IT_WORKS.md as HTML, or None if unavailable."""
    path = _BASE.parent.parent / "docs" / "HOW_IT_WORKS.md"
    try:
        return _render_explainer_cached(str(path), path.stat().st_mtime)
    except (OSError, FileNotFoundError):
        return None


@lru_cache(maxsize=2)
def _render_explainer_cached(path: str, _mtime: float) -> Optional[str]:
    import re

    try:
        import markdown
        raw = pathlib.Path(path).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - never take the site down for a doc
        return None
    # Repo-relative links do not resolve as URLs on the site; keep the words,
    # drop the broken href rather than shipping a page of dead links.
    raw = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\)", r"", raw)
    return markdown.markdown(raw, extensions=["tables", "fenced_code"])


def _corpus_facts() -> dict:
    """The landing page's headline numbers, DERIVED from the corpus_facts mart.

    Never typed into the template. The README carried ten hand-written numbers
    that all rotted (2026-07-31); the one page a first-time visitor reads is the
    worst possible place to repeat that. `mtime` keys the cache so a mart
    rebuild is picked up without a restart.
    """
    path = _MARTS_DIR / "corpus_facts.parquet"
    try:
        return _corpus_facts_cached(str(path), path.stat().st_mtime)
    except (OSError, FileNotFoundError):
        return {}


@lru_cache(maxsize=4)
def _corpus_facts_cached(path: str, _mtime: float) -> dict:
    try:
        import pandas as pd
        df = pd.read_parquet(path)
        return {} if df.empty else {k: v for k, v in df.iloc[0].to_dict().items()}
    except Exception:  # noqa: BLE001 - a missing mart must not take the site down
        return {}


def _exemplar_track() -> Optional[str]:
    """One analyzed track to deep-link the 83-feature page from the landing.

    That page is the demo's strongest artifact ("I measured this from audio, it
    is not a Spotify API call") and it used to sit three clicks deep behind a
    library search. Deterministic so the demo link never moves under you.
    """
    try:
        rows = _feature_cache().library_rows()
        analyzed = sorted(r["id"] for r in rows
                          if r.get("analyzed") and r.get("source_url"))
        return analyzed[0] if analyzed else None
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _feature_store() -> Optional[FeatureStore]:
    """The gold corpus — used only for the RAG feature glossary now. None if unbuilt."""
    try:
        return FeatureStore(config.MODELED_DIR)
    except FileNotFoundError as exc:
        logger.warning("Feature store unavailable (%s) — RAG glossary disabled.", exc)
        return None


@lru_cache(maxsize=1)
def _looks_rate_limited(exc: BaseException) -> bool:
    """Is this Spotify throttling us, rather than something being broken?

    Checked by shape, not by type: spotipy raises SpotifyException for a 429 but
    a RetryError/MaxRetryError from urllib3 when the adapter gives up on repeated
    503s — the live log showed BOTH for the same underlying cause. Getting this
    wrong only softens the wording, never the status."""
    status = getattr(exc, "http_status", None) or getattr(exc, "code", None)
    if status in (429, 503):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(s in text for s in ("429", "rate/request limit", "too many",
                                   "max retries", "503"))


def _feature_cache() -> FeatureCache:
    """The shared, track-keyed feature cache (Epic A) — the dashboard's feature source."""
    return FeatureCache()


def _collapse_twin_rows(ranges: list[dict], dupes: dict[str, str]) -> list[dict]:
    """Collapse a range's DISPLAY list to one row per recording (O3a): each
    track takes its canonical id (so links/features resolve canonically) and
    repeats are dropped keeping the first — the user's familiar rank and
    fetched title survive on the surviving row."""
    for rng in ranges:
        seen: set[str] = set()
        kept = []
        for t in rng["tracks"]:
            canon = dupes.get(t["id"], t["id"])
            if canon in seen:
                continue
            seen.add(canon)
            kept.append({**t, "id": canon})
        rng["tracks"] = kept
    return ranges


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
        df = fetch_top_tracks(time_range=key, limit=_TOP_LIMIT, sp=client)
        tracks, ids_here = [], []
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                tid = r["spotify_track_id"]
                name, artist = r.get("track_name", ""), r.get("artist_names", "")
                all_ids.append(tid)
                ids_here.append(tid)
                meta_items.append(
                    {"spotify_track_id": tid, "track_name": name, "artist_names": artist,
                     "popularity": r.get("popularity"), "duration_ms": r.get("duration_ms"),
                     # P3.1: display context the fetch already carries (art for
                     # library/guest-dashboard; artist id hardens the artist join)
                     "album_image_url": r.get("album_image_url"),
                     "primary_artist_id": r.get("primary_artist_id")})
                pop = r.get("popularity")
                tracks.append({"rank": int(r.get("rank", 0)), "name": name,
                               "artist": artist, "id": tid, "art": r.get("album_image_url"),
                               "popularity": int(pop) if pop is not None else None})
        per_range_ids[key] = ids_here
        ranges.append({"key": key, "label": label, "tracks": tracks})

    # The shared cache: remember metadata (for the worker's search), queue
    # misses, then canonicalize. ORDER MATTERS (O3a): enqueue's intake guard is
    # what flags a brand-new twin, so canonicalization runs AFTER it — and all
    # derived values (cached/coverage/profile/drift) are built from the
    # CANONICAL ids so the same recording never votes twice (red-team #3).
    cache.remember_meta(meta_items)
    cache.enqueue(all_ids)               # misses → extraction queue (idempotent)
    dupes = cache.duplicate_flags()
    per_range_ids = canonicalize_range_ids(per_range_ids, dupes)
    all_ids = canonicalize_ids(all_ids, dupes)
    ranges = _collapse_twin_rows(ranges, dupes)
    cached = cache.get(all_ids)          # {id: features} — the visitor's OWN analyzed songs
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
        "artists": _top_artists(client, cache),
        "coverage": {"analyzed": coverage["cached"], "total": coverage["total"],
                     "analyzing": coverage["queued"] + coverage["running"]},
        "track_total": len(set(all_ids)),
    }


def guest_dashboard_context(prof: dict[str, Any], cache: FeatureCache) -> dict[str, Any]:
    """The guest DASHBOARD replica (P3.5, owner ask): the same context shape as
    build_dashboard_context, built ENTIRELY from the snapshot's ids + the cache —
    zero Spotify calls, zero enqueue (guests are read-only, D-30). Display data
    is DERIVED, not carried in the snapshot (journal #27): art/popularity from
    track_meta via library_rows, artist genres/images from artist_meta (P3.1).
    O3a: canonicalized at READ, so a pre-O3 snapshot (the live one carries 10
    twins whose canonicals are also present) single-counts without re-snapshot."""
    dupes = cache.duplicate_flags()
    range_ids = canonicalize_range_ids(
        {w: list(ids) for w, ids in (prof.get("range_ids") or {}).items()}, dupes)
    all_ids = [t for ids in range_ids.values() for t in ids]
    cached = cache.get(all_ids)
    meta = {r["id"]: r for r in cache.library_rows()}
    labels = dict(_TIME_RANGES)
    ranges = []
    for key, ids in range_ids.items():
        tracks = []
        for i, tid in enumerate(ids, start=1):
            m = meta.get(tid, {})
            tracks.append({
                "rank": i, "id": tid,
                "name": m.get("name") or tid, "artist": m.get("artist") or "",
                "art": m.get("art"), "popularity": m.get("popularity"),
                "analyzed": tid in cached,
                "feat": track_summary(cached.get(tid)),
            })
        ranges.append({"key": key, "label": labels.get(key, key), "tracks": tracks})
    ameta = cache.all_artist_meta()
    by_name = {a.get("artist_name", "").lower(): a for a in ameta.values()}
    artists = []
    for a in prof.get("artists", []):
        stored = by_name.get((a.get("name") or "").lower(), {})
        artists.append({"name": a.get("name", ""),
                        "genres": stored.get("genres") or a.get("genres", ""),
                        "image": stored.get("image_url"),
                        # D-54: guests get the same profile links (the snapshot
                        # carries names; the id comes from stored artist_meta)
                        "artist_id": stored.get("artist_id")})
    per_range_rows = {k: [cached[i] for i in ids if i in cached]
                      for k, ids in range_ids.items()}
    return {
        "ranges": ranges,
        "range_ids": range_ids,
        "profile": absolute_profile(list(cached.values())),
        "drift": drift_over_rows(per_range_rows),
        "artists": artists,
        "coverage": {"analyzed": len(cached), "total": len(set(all_ids)), "analyzing": 0},
        "track_total": len(set(all_ids)),
    }


def _top_artists(client: Any, cache: Optional[FeatureCache] = None,
                 limit: int = 12) -> list[dict[str, Any]]:
    """The visitor's top artists (with Spotify genres — which tracks don't expose).

    P3.1/D-36: when a cache is supplied, the fetched frame is ALSO persisted to
    artist_meta — the same data used to be thrown away after render; persisting
    it is what makes genres/popularity servable to /artists with zero extra API
    calls. Best-effort: a persist failure never breaks the dashboard."""
    try:
        df = fetch_top_artists(time_range="medium_term", limit=limit, sp=client)
    except Exception:  # noqa: BLE001 — a nice-to-have section, never fatal
        return []
    if df is None or df.empty:
        return []
    if cache is not None:
        try:
            cache.remember_artists(df.to_dict("records"))
        except Exception:  # noqa: BLE001 — persistence is additive, never fatal
            logger.warning("artist_meta persist failed (dashboard unaffected)")
    return [
        {
            "name": r.get("artist_name", ""),
            "genres": r.get("genres", ""),
            "image": r.get("image_url"),
            # D-54: the dashboard cards link to /artist/{id}. The id was always
            # in this frame (it is what remember_artists keys on) and was simply
            # dropped on the way to the template — so the link costs no API call.
            "artist_id": r.get("artist_id"),
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
    # QA-2: openapi_url=None completes the intent docs_url/redoc_url already
    # expressed. /docs was closed but /openapi.json still served the full schema
    # to anonymous callers — every path including the owner-only repair routes,
    # with parameter shapes. The gates hold regardless, so this is hardening, not
    # a vulnerability: it stops handing out the owner-surface map for free.
    app = FastAPI(title="Vercillo Analytics", docs_url=None, redoc_url=None,
                  openapi_url=None)
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

    def _is_viewer(session: dict[str, Any]) -> bool:
        """A viewer may read the corpus/analytics surfaces: a logged-in user OR a
        read-only guest (H7 demo). Actions that need a token or write (login,
        dashboard fetch, /ask, /classify) still require real auth."""
        return auth_web.is_authenticated(session) or bool(session.get("is_guest"))

    def _same_user(a: Optional[str], b: Optional[str]) -> bool:
        """Spotify user ids are not case-sensitive in practice, and a pasted
        value picks up stray whitespace — compare them the way a human means
        them. Still an EXACT identity check: only case/padding is forgiven."""
        if not a or not b:
            return False
        return a.strip().casefold() == b.strip().casefold()

    def _is_owner(session: dict[str, Any]) -> bool:
        """D-56 repair gate: authed AND the session's Spotify /me id equals
        WEBAPP_OWNER_SPOTIFY_ID (case/whitespace-insensitive). Fail-closed:
        env unset, anon, guests, or an undeterminable /me id all read False.
        The id is cached in the session after the first check (one
        borrowed-time /me call, then free)."""
        owner = config.owner_spotify_id()
        if not owner or not auth_web.is_authenticated(session):
            return False
        mid = session.get("me_id")
        if not mid:
            try:
                mid = fetch_user_profile(
                    auth_web.client_from_session(session)).get("user_id")
            except Exception:  # noqa: BLE001 — /me is borrowed-time garnish
                mid = None
            if mid:
                session["me_id"] = mid
        if mid and not _same_user(mid, owner):
            # Fail-closed is right, but silent-and-wrong is miserable to debug:
            # say the id we SAW so a typo'd WEBAPP_OWNER_SPOTIFY_ID is a
            # one-line log read, not a mystery. Local gitignored log only.
            logger.info("repair gate: signed-in id %r != WEBAPP_OWNER_SPOTIFY_ID %r",
                        mid, owner)
        return _same_user(mid, owner)

    def _needs_source(cache: FeatureCache, track_id: Optional[str] = None):
        """The repair queue (D-56): every track that is blank and will STAY blank
        without a manual source, and that no provenance row has since resolved.
        With `track_id` → that track's reason or None (cheap single-row check);
        without → {id: reason}.

        TWO populations, because the ledger alone was not the whole truth: the
        re-extraction runner and the quarantine scripts write ledger entries, but
        a track the ORDINARY worker dead-letters (failed at MAX_ATTEMPTS) never
        got one — so it sat blank, unretried and invisible to this very filter,
        which is the one place the owner would look for it."""
        try:
            failed = (json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
                      .get("failed") or {})
        except (OSError, ValueError):
            failed = {}
        if track_id is not None:
            if cache.provenance_for(track_id) is not None:
                return None
            reason = (failed.get(track_id) or {}).get("error")
            if reason:
                return reason
            return ("acquisition gave up after repeated attempts — needs a source"
                    if track_id in cache.dead_lettered_ids() else None)
        done = {r["spotify_track_id"] for r in cache.all_provenance()}
        out = {t: (info or {}).get("error", "") for t, info in failed.items()
               if t not in done}
        for t in cache.dead_lettered_ids():
            if t not in done and t not in out:
                out[t] = "acquisition gave up after repeated attempts — needs a source"
        return out

    def _viewer_flags(session: dict[str, Any]) -> dict[str, Any]:
        """Template flags: `authed` = real login (Log out, personal actions),
        `guest` = demo persona (banner), `viewer` = either (nav + read surfaces)."""
        authed = auth_web.is_authenticated(session)
        guest = bool(session.get("is_guest"))
        return {"authed": authed, "guest": guest, "viewer": authed or guest}

    def _log_turn(session: dict[str, Any], *, mode: str, question: Optional[str],
                  result: dict[str, Any], latency_ms: int,
                  error: Optional[str] = None) -> None:
        """Record one LLM-surface turn (D-47 — log every prompt + response).
        `chat_session_id` is a per-browser-session uuid, NEVER the auth sid.
        Best-effort: the cache method never raises."""
        sid = session.get("chat_sid")
        if not sid:
            sid = session["chat_sid"] = uuid.uuid4().hex
        n = session.get("chat_turn", 0)
        _feature_cache().log_chat_turn(
            chat_session_id=sid, turn_index=n, mode=mode,
            # K2c: tool-loop turns stamp their own contract version and carry
            # depth + a degrade reason; single-shot modes keep the module's.
            prompt_version=result.get("prompt_version") or PROMPT_VERSION,
            user_question=question,
            rendered_context=result.get("grounding"),
            raw_model_output=result.get("raw"),
            parsed_answer=result.get("answer") or result.get("narrative"),
            cited_entities=result.get("cited"), source=result.get("source"),
            model=result.get("model"), latency_ms=latency_ms,
            depth=result.get("depth"), error=error or result.get("error"))
        session["chat_turn"] = n + 1

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        authed = auth_web.is_authenticated(request.state.session)
        return templates.TemplateResponse(request, "index.html",
                                          {"authed": authed,
                                           "has_demo": load_demo_profile() is not None,
                                           "facts": _corpus_facts(),
                                           "exemplar": _exemplar_track()})

    @app.get("/eras", response_class=HTMLResponse)
    def eras(request: Request):
        """Decade-grain view of the corpus. PUBLIC — these are corpus facts on
        the same terms as /library and /artists, and it is the surface most
        likely to be opened by someone with no account.

        Reads `era_profile.parquet`. When the mart is absent (a fresh clone, or
        CI, where `data/` is gitignored) this renders an honest empty state
        rather than redirecting: a nav link that bounces you to the home page
        reads as broken, and it would make the route's status depend on whether
        the machine happens to hold a corpus.
        """
        from . import eras as eras_mod

        rows = eras_mod.era_rows(_load_mart("era_profile"))
        return templates.TemplateResponse(request, "eras.html", {
            **_viewer_flags(request.state.session),
            "rows": rows,
            "summary": eras_mod.era_summary(rows),
            "min_tracks": eras_mod.MIN_TRACKS,
            "loudness_chart": eras_mod.era_chart_svg(
                rows, "mean_loudness_db", "Mean loudness", " dBFS"),
            "duration_chart": eras_mod.era_chart_svg(
                rows, "mean_duration_sec", "Mean track length", " s")})

    @app.get("/how-it-works", response_class=HTMLResponse)
    def how_it_works(request: Request):
        """Serve the plain-language explainer the repo already maintains.

        PUBLIC and no login: a colleague sent this link should be able to
        understand what the thing is without an account. Rendered from
        `docs/HOW_IT_WORKS.md` rather than re-written into a template — that
        file is tested for structure (`test_docs_structure.py`) and its numbers
        are generated (`docs_facts.py`), and a second hand-typed copy would rot
        exactly the way the README's ten numbers did.

        The links in that document are relative repo paths (`concepts/…`,
        `../CLAUDE_INSTRUCTIONS.md`) which do not resolve as URLs here, so they
        are unwrapped to plain text rather than rendered as broken links.
        """
        body = _render_explainer()
        if body is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "how_it_works.html",
            {**_viewer_flags(request.state.session), "body": body})

    @app.get("/login")
    def login(request: Request):
        url = auth_web.build_authorize_url(request.state.session)
        return RedirectResponse(url, status_code=307)

    @app.get("/guest")
    def guest(request: Request):
        """Enter read-only DEMO mode (H7, D-30): load the owner's saved taste
        snapshot into the session and show the full analytics — no login, no
        5-seat gate. The interview showpiece. Guests never fetch Spotify or
        enqueue (all snapshot tracks are already cached)."""
        session = request.state.session
        # QA-2: never clobber a LOGGED-IN session. This route overwrites
        # session["taste"] with the owner's published snapshot and sets is_guest,
        # so a pilot user who clicked the demo link saw the owner's snapshot
        # rendered as their own on /analytics, /explore, /artists and in their
        # /chat grounding until they next hit /dashboard. No token leaked and no
        # privilege changed — a trust bug, not a breach, and one line to close.
        if auth_web.is_authenticated(session):
            return RedirectResponse("/dashboard", status_code=303)
        prof = load_demo_profile()
        if prof is None:
            return RedirectResponse("/", status_code=303)
        cache = _feature_cache()
        # O3a: canonicalize at READ (red-team #3 — the live snapshot carries 10
        # twins whose canonicals are also present; guests double-counted).
        range_ids = canonicalize_range_ids(
            {w: list(ids) for w, ids in (prof.get("range_ids") or {}).items()},
            cache.duplicate_flags())
        all_ids = [t for ids in range_ids.values() for t in ids]
        cached = cache.get(all_ids)
        per_range_rows = {w: [cached[i] for i in ids if i in cached]
                          for w, ids in range_ids.items()}
        session["is_guest"] = True
        session["taste"] = {
            "range_ids": range_ids,
            "artists": prof.get("artists", []),
            "drift": drift_over_rows(per_range_rows),
            "coverage": {"analyzed": len(cached), "total": len(set(all_ids)), "analyzing": 0},
        }
        # P3.5: guests land on the DASHBOARD replica (the full experience),
        # not straight at /analytics.
        return RedirectResponse("/dashboard", status_code=303)

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
        # A real login SUPERSEDES the demo persona. `rotate` preserves session
        # DATA, so without this `is_guest` survives the login and never clears —
        # the visitor stays flagged a guest forever, sees the demo banner on
        # every page, and hitting Back lands on the owner's snapshot instead of
        # their own library. Owner-reported: "when I click back it brings me to
        # the demo". The stale demo taste goes too, so /analytics and /explore
        # can't render snapshot numbers to a logged-in user before /dashboard
        # rebuilds their real ones.
        session = request.state.session
        session.pop("is_guest", None)
        session.pop("taste", None)
        # Session-fixation defense: fresh id now that we're authenticated.
        request.state.sid = _store.rotate(request.state.sid)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        session = request.state.session
        if not auth_web.is_authenticated(session):
            # The guest replica (P3.5): snapshot ids + cache, read-only, no
            # fetch/enqueue. Anyone else → home.
            if session.get("is_guest"):
                prof = load_demo_profile()
                if prof is None:
                    return RedirectResponse("/", status_code=303)
                ctx = guest_dashboard_context(prof, _feature_cache())
                return templates.TemplateResponse(
                    request, "dashboard.html", {**ctx, **_viewer_flags(session)})
            return RedirectResponse("/", status_code=303)
        try:
            client = auth_web.client_from_session(session)
            ctx = build_dashboard_context(client, _feature_cache())
        except auth_web.AuthError as exc:
            # The TOKEN is the problem — this session cannot be recovered, so
            # dropping it and asking for a fresh login is the honest move.
            logger.warning("dashboard auth failed: %s", exc)
            _store.delete(request.state.sid)
            request.state.sid = _store.new()
            return templates.TemplateResponse(
                request, "error.html",
                {"detail": "Your Spotify session expired — please log in again.",
                 "authed": False}, status_code=401)
        except Exception as exc:  # noqa: BLE001 — upstream hiccup, not our death
            # NEVER 502 here. 502 is in the H5 fallback Worker's ORIGIN_DOWN set
            # (502/504/521-523/530), so a Spotify rate limit — which is what
            # this almost always is — made Cloudflare replace the page with
            # "Demo offline", telling the visitor the whole site was down when
            # the app was healthy and simply couldn't reach Spotify. 503 says
            # "temporarily unavailable, come back" and passes through as OUR
            # page. (Owner report 2026-07-25: "it's when I try to log in".)
            #
            # And the session SURVIVES. Deleting it logged the visitor out over
            # a transient upstream error, so recovering meant logging in again —
            # more API calls, deeper into the same rate limit, a loop that got
            # worse the harder you tried.
            logger.exception("dashboard build failed")
            throttled = _looks_rate_limited(exc)
            detail = ("Spotify is rate-limiting us right now — that's a limit on "
                      "how fast we may read your library, not a problem with your "
                      "account or this app. You're still logged in; it clears on "
                      "its own in a minute."
                      if throttled else f"Could not load your data: {exc}")
            return templates.TemplateResponse(
                request, "error.html",
                {"detail": detail, "authed": True, "retry": "/dashboard"},
                status_code=503, headers={"Retry-After": "60"})
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
        t0 = time.monotonic()
        result = TasteRAG(_feature_store()).answer(question, taste)
        _log_turn(session, mode="adhoc", question=question, result=result,
                  latency_ms=int((time.monotonic() - t0) * 1000))
        return templates.TemplateResponse(request, "ask.html", {
            "authed": True, "question": question,
            "answer": result["answer"], "source": result["source"],
            "model": result.get("model"),
        })

    _CHAT_HISTORY_MAX = 20  # display turns kept (drop-oldest); D-43

    @app.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request):
        """Talk to your data (Epic K, STORY-LED). Viewer-gated (authed + guest,
        like /explore). Opens with gemma4's generated data STORY (its strength,
        K1 probe); the visitor then asks ad-hoc follow-ups. Each turn is answered
        against the frozen taste grounding (reliable > multi-turn drift) and
        logged (D-47)."""
        session = request.state.session
        if not _is_viewer(session):
            return RedirectResponse("/", status_code=303)
        taste = session.get("taste")
        if not taste:  # need a dashboard/guest load first
            return RedirectResponse("/dashboard" if auth_web.is_authenticated(session)
                                    else "/", status_code=303)
        # the opening story — generated once per session, then cached + logged
        if not session.get("chat_story"):
            t0 = time.monotonic()
            r = TasteRAG(_feature_store()).story(taste)
            _log_turn(session, mode="story", question=None, result=r,
                      latency_ms=int((time.monotonic() - t0) * 1000))
            session["chat_story"] = {"text": r["answer"], "source": r["source"]}
        return templates.TemplateResponse(request, "chat.html", {
            **_viewer_flags(session), "story": session["chat_story"],
            "history": session.get("chat_history") or []})

    @app.post("/chat", response_class=HTMLResponse)
    def chat_ask(request: Request, q: str = Form("")):
        session = request.state.session
        if not _is_viewer(session):
            return RedirectResponse("/", status_code=303)
        taste = session.get("taste")
        question = (q or "").strip()
        if not taste or not question:
            return RedirectResponse("/chat", status_code=303)
        t0 = time.monotonic()
        result = TasteRAG(_feature_store()).answer(question, taste)
        _log_turn(session, mode="adhoc", question=question, result=result,
                  latency_ms=int((time.monotonic() - t0) * 1000))
        history = session.get("chat_history") or []
        history.append({"q": question, "a": result["answer"], "source": result["source"]})
        session["chat_history"] = history[-_CHAT_HISTORY_MAX:]  # drop-oldest
        return RedirectResponse("/chat", status_code=303)  # PRG — refresh-safe

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
                               "drift": taste.get("drift"),
                               "taxonomy": archetype_taxonomy()}  # N2: static reference grid
        # Signature works even before any model is trained (population stats only).
        # O3b: twins sit out of the population (one recording, one vote).
        twins = cache.twin_ids()
        # PROJECTION, not the 82-col contract: the signature reads exactly the
        # 8 _SIGNATURE_DIMS columns, and `all_features()` dragged the whole dict
        # plus the display arrays across the wire for them. Measured on the live
        # 1,946-track corpus (2026-07-29, warm best-of-3): 280 ms / 6.5 MB →
        # 54 ms / 0.6 MB, 5.1x faster and 10.3x lighter, with zero value
        # differences; both grow linearly with the corpus. Guarded by
        # test_analytics_population_never_reads_the_heavy_json_columns.
        population = [f for tid, f in
                      cache.feature_columns([c for c, *_ in _SIGNATURE_DIMS]).items()
                      if tid not in twins]
        ctx["signature"] = acoustic_signature(list(cached.values()), population)

        # Taste vs popularity (slice P) — fetched context, absent-safe: renders
        # only when enough popularity values have been seen (the field is
        # deprecated upstream and may be missing entirely).
        pops = cache.all_popularity()
        ctx["popularity"] = popularity_context(
            [pops[t] for t in set(all_ids) if t in pops], list(pops.values()))

        # Average loudness arc (F-v2 roll-up) — the shape of a typical track in
        # the user's rotation; needs no trained model, absent-safe under 5 curves.
        arc = average_loudness_arc(
            list(cache.loudness_curves(list(set(all_ids))).values()))
        ctx["loudness_arc"] = {"svg": loudness_arc_svg(arc), "n": arc["n"]} if arc else None

        model = cl.latest_model(cache, "song")
        if model is not None:
            ctx["trained"] = True
            assigned = cl.track_assignments(cache, model.id)
            # F14: a GET must not WRITE. This used to call the persisting
            # `assign_track`, so rendering /analytics wrote cluster rows — and
            # before D-62's coverage fix it wrote them from a model fitted on
            # 37% of the corpus. The pure version keeps the visitor's own
            # tracks on the map (they may post-date the last training run)
            # without persisting anything; the worker's post-drain retrain is
            # what makes an assignment durable.
            for tid, feats in cached.items():
                if tid not in assigned:
                    cid = cl.nearest_cluster(model, feats)
                    if cid is not None:
                        assigned[tid] = {"cluster_id": cid, "map_x": None, "map_y": None}

            labels: dict[str, str] = model.labels
            per_window = {w: [assigned[t]["cluster_id"] for t in ids if t in assigned]
                          for w, ids in range_ids.items()}
            ctx["composition"] = cluster_composition(per_window, labels)
            # K3: grounded bucket descriptions ride the model row (additive —
            # pre-K3 models read None and the legend renders name-only).
            descs = getattr(model, "descriptions", None) or {}
            ctx["legend"] = [{"cluster_id": int(c), "label": lbl,
                              "color": cluster_color(int(c)),
                              "description": str((descs.get(c) or {}).get("text") or ""),
                              "source": str((descs.get(c) or {}).get("source") or "")}
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
            # journal #27 / #60: a caption that RESTATES a computed value is a
            # second copy of it. "Every cached song" was wrong by 64% while the
            # model covered 37% of the corpus, and no test could see it because
            # the sentence was a literal. Derived, it cannot drift again.
            # Count what is DRAWN, not what is in the list: the F14 in-memory
            # assignments carry cluster_id but no map coordinates, so they ride
            # in `population_pts` and never reach the SVG. Counting the list
            # over-stated the map by exactly those 4 tracks on the live corpus —
            # the same restates-a-computed-value bug in miniature, caught by
            # comparing the caption to the rendered <circle> count.
            ctx["map_counts"] = {
                "plotted": sum(1 for p in population_pts
                               if p["x"] is not None and p["y"] is not None),
                "analyzed": len(cache.analyzed_ids()),
                "yours": len(user_pts)}

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
        if not _is_viewer(session):
            return RedirectResponse("/", status_code=303)
        ctx = _analytics_context(session)
        if ctx is None:
            return RedirectResponse(
                "/dashboard" if auth_web.is_authenticated(session) else "/", status_code=303)
        return templates.TemplateResponse(request, "analytics.html",
                                          {**ctx, **_viewer_flags(session)})

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
        t0 = time.monotonic()
        result = TasteRAG(_feature_store()).classify(session["taste"])
        _log_turn(session, mode="profile", question=None, result=result,
                  latency_ms=int((time.monotonic() - t0) * 1000))
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
            # Derived, never asserted: the gray "not yet clustered" dots were
            # 62% of this chart while the model was stale, and the caption
            # claimed nothing about it (journal #60).
            "scatter_counts": {
                "total": len(points),
                "clustered": sum(1 for p in points if p.get("cluster_id") is not None),
                "plotted": explore_mod.scatter_plotted_count(points, user_set)},
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
        # "more like this": the seed's own values become VISIBLE targets. B1 —
        # re-fill when the seed CHANGED (vs the hidden prev_seed the form was last
        # filled from), not only when targets are empty, else a new seed's values
        # never override the previous seed's still-in-the-form targets.
        constraints = apply_seed_targets(
            seed, params.get("prev_seed") or "", constraints,
            perceptual.get(seed) if seed else None, allowed, pops.get(seed))

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
        # P4.7.5: this listed EVERY analyzed track — 1,894 <option> elements,
        # ~117 KB of markup, and nobody scrolls 1,894 options, so it was weight
        # AND an unusable control. Bounded to the visitor's OWN analyzed tracks
        # (what you actually seed from); any other song is still seedable from
        # its /song page via "More like this — tune it", which is the path that
        # already existed. Capability unchanged, control usable.
        _my_ids = [t for ids in (taste.get("range_ids") or {}).values() for t in ids]
        seed_options = sorted(
            ({"id": t, "name": (meta.get(t) or {}).get("track_name") or t}
             for t in dict.fromkeys(_my_ids) if t in perceptual),
            key=lambda o: o["name"].lower())
        feature_rows = catalog[["column", "friendly", "tier", "unit"]].to_dict("records")
        feature_rows.append({"column": "popularity", "friendly": "Popularity",
                             "tier": "fetched", "unit": "0–100"})
        return {"authed": True, "built": True, "seed": seed,
                "seed_name": (meta.get(seed) or {}).get("track_name") if seed else None,
                "form": form, "features": feature_rows,
                "seed_options": seed_options, "results": results,
                "active": bool(constraints)}

    # ── the Artists surface (Epic P / P3.2) ─────────────────────────────────
    _ARTIST_ID_RE = re.compile(r"[0-9A-Za-z]{8,40}")  # base62 guard (id → URL/queries)

    # Borrowed-time garnish memo (session-36 fix): the artist page re-fetched the
    # live top-10 on EVERY view + analyze redirect — heavy browsing rate-limited
    # the endpoint and, with spotipy's old retry/Retry-After behavior, "the
    # artists page gets stuck". Non-empty results memoize for 10 min; empty/dark
    # results are NOT cached (the endpoint may come back). On app.state for tests.
    _ARTIST_TOP_TTL = 600.0
    artist_top_cache: dict[str, tuple[float, Any]] = {}
    app.state.artist_top_cache = artist_top_cache

    def _artist_top_cached(artist_id: str, session: dict[str, Any]):
        now = time.monotonic()
        hit = artist_top_cache.get(artist_id)
        if hit is not None and now - hit[0] < _ARTIST_TOP_TTL:
            return hit[1]
        try:
            df = fetch_artist_top_tracks(artist_id, auth_web.client_from_session(session))
        except Exception:  # noqa: BLE001 — garnish, never fatal
            df = None
        if df is not None and not df.empty:
            artist_top_cache[artist_id] = (now, df)
        return df
    _TRACK_ID_RE = re.compile(r"[0-9A-Za-z]{1,64}")   # base62; rejects path-traversal on public /song

    @app.get("/artists", response_class=HTMLResponse)
    def artists_view(request: Request):
        """R1 (P4.7.2): the CORPUS artist index — PUBLIC, paginated, searchable.

        Was viewer-gated and built from `session["taste"]["artists"]`, so it
        showed ~15 artists while the corpus knew ~915 and an anonymous visitor
        reached none of them. Building from the corpus is also what makes the
        surface taste-free and therefore publishable (D-18) — the same
        population-only move that made /library public, with no builder
        refactor needed.

        The 'Your artists' tab overlays a viewer's own top artists on top.
        """
        session = request.state.session
        params = dict(request.query_params)
        flags = _viewer_flags(session)
        cache = _feature_cache()
        index = corpus_artist_index(cache.all_meta(), cache.all_perceptual(),
                                    cache.all_artist_meta(), cache.library_rows())
        tab = params.get("tab") if params.get("tab") in ("all", "mine") else "all"
        if tab == "mine" and not flags["viewer"]:
            tab = "all"                        # anon can't land on a personal tab
        taste = session.get("taste") or {}
        my_names = {(a.get("name") or "") for a in (taste.get("artists") or [])}
        my_count = len(my_names) if flags["viewer"] else 0

        v = artists_view_mod.artists_view(
            index, q=(params.get("q") or "").strip(),
            genre=params.get("genre") or "",
            mine_names=my_names if tab == "mine" else None)
        # Filtering ran over the whole index above; this only slices it.
        page = library_view_mod.page_slice(v, page=params.get("page"),
                                           per=params.get("per"))
        # The chart compares what is ON SCREEN — over 915 artists it would be
        # unreadable, and over a filtered set it answers the question asked.
        catalog = load_catalog()
        features = (catalog[["column", "friendly"]].to_dict("records")
                    if catalog is not None else
                    [{"column": c, "friendly": c.title()}
                     for c in ("energy", "tempo", "danceability")])
        chosen = params.get("f") if any(
            r["column"] == params.get("f") for r in features) else "energy"
        friendly = next((r["friendly"] for r in features if r["column"] == chosen), chosen)
        return templates.TemplateResponse(request, "artists.html", {
            **flags, "tab": tab, "cards": page["page_rows"],
            "shown": v["shown"], "total": v["total"], "my_count": my_count,
            # The heading renders "<shown> of <total_cards>" when a filter is
            # on; the template referenced a name nothing supplied, so it read
            # "N of  artists" on every ?genre= page.
            "total_cards": v["total"],
            "n_linkable": v["n_linkable"], "n_with_genres": v["n_with_genres"],
            "n_name_keyed": v["n_name_keyed"], "n_folded": v["n_folded"],
            "q": v["q"], "genre": v["genre"],
            "strip": genre_strip(v["rows"]),
            "page": page["page"], "pages": page["pages"], "per": page["per"],
            "is_all": page["is_all"], "from_index": page["from_index"],
            "to_index": page["to_index"], "page_sizes": page["page_sizes"],
            "pager": library_view_mod.page_links(params, page, base="/artists"),
            "all_url": "/artists?" + library_view_mod.pager_query(
                params, per="all", page=None),
            "chart": comparison_svg(page["page_rows"], chosen, friendly),
            "features": features, "chosen": chosen, "friendly": friendly})

    @app.get("/artist/{artist_id}", response_class=HTMLResponse)
    def artist_page(request: Request, artist_id: str):
        """R1/R2: PUBLIC, on the same terms as /artists and /song — the
        discography and acoustic profile are corpus facts. The listening-derived
        "your top tracks" and the borrowed-time live top-10 stay personal and
        authed respectively; each degrades to an honest caption instead of
        gating the whole page.
        """
        session = request.state.session
        if not _ARTIST_ID_RE.fullmatch(artist_id or ""):
            return RedirectResponse("/artists", status_code=303)
        cache = _feature_cache()
        am = cache.all_artist_meta().get(artist_id)
        if am is None:
            return RedirectResponse("/artists", status_code=303)
        name = am.get("artist_name") or artist_id
        taste = session.get("taste") or {}
        metas = cache.all_meta()
        perceptual = cache.all_perceptual()
        card = artist_rollup([{"name": name}], metas, perceptual, {artist_id: am})[0]

        # R2: the discography, from metadata D-70 captured — no API call, and
        # no MusicBrainz (D-61 deferred it; the remaster caveat is stated in
        # the template rather than silently corrected).
        lib_rows = cache.library_rows()
        # Name-matching, but only where a name cannot CONTRADICT an id. The
        # corpus index deliberately keeps an id-keyed artist and a name-keyed
        # one apart — two acts genuinely share a name often enough that fusing
        # them would attribute someone else's catalogue to this page, and the
        # drift and acoustic profile would then describe a chimera. This page
        # was fusing exactly what the index splits (director review
        # 2026-07-31). A track that carries a DIFFERENT primary_artist_id is
        # now never claimed; one that carries none is the unresolved case the
        # name match exists for, and the page says how many it took.
        by_id, by_name = [], []
        for r in lib_rows:
            pid = r.get("primary_artist_id")
            if pid == artist_id:
                by_id.append(r["id"])
            elif not pid and artists_view_mod.primary_artist(
                    r.get("artist") or "").lower() == name.lower():
                by_name.append(r["id"])
        their_tids = by_id + by_name
        albums = artists_view_mod.artist_albums(
            their_tids, cache.all_track_identity(), perceptual,
            {r["id"]: r.get("art") for r in lib_rows})
        ctx_albums = {
            "albums": albums,
            "n_by_id": len(by_id), "n_by_name": len(by_name),
            "n_albums": len(albums),
            "n_dated": sum(1 for a in albums if a["year"]),
            # R4a: how their sound moved across their OWN catalogue — an artist
            # fact, so it renders for anonymous visitors too.
            # `loudness_db`, not `energy`: energy is a percentile RANK against the
            # current corpus, so another artist's tracks arriving would move
            # THIS artist's "drift" without a note of their music changing.
            "drift": artists_view_mod.artist_drift(albums, "loudness_db"),
        }
        # R3: their acoustic character vs the corpus + their SPREAD. Projected
        # to the signature columns only (the P4.6.2 rule — no all_features on a
        # request path), and reusing analytics.acoustic_signature so the words
        # and the ±2σ cap stay in one place (P4.7.0).
        _sig_cols = [c for c, *_ in _SIGNATURE_DIMS]
        _sig_feats = cache.feature_columns(_sig_cols)
        _excl = cache.excluded_from_aggregates()
        ctx_albums["profile"] = artists_view_mod.artist_signature(
            their_tids, _sig_feats,
            [f for t, f in _sig_feats.items() if t not in _excl])

        yours = your_top_by_artist(name, taste.get("range_ids") or {}, metas)
        analyzed_ids = cache.cached_ids([t["id"] for t in yours])
        for t in yours:
            t["analyzed"] = t["id"] in analyzed_ids

        # "similar in your library" — acoustic centroids, links where ids known
        # (O3b: twin-free features so a double-release can't tilt a centroid)
        _tw = cache.twin_ids()
        # PROJECTION: nearest_artists z-scores the _SIMILARITY_COLS subset, so
        # the 82-col dict + display arrays never need to leave the DB (the
        # /analytics fix, applied to the second request path that had it).
        sim = nearest_artists(name,
                              {t: f for t, f in
                               cache.feature_columns(_SIMILARITY_COLS).items()
                               if t not in _tw}, metas)
        name_to_id = {(a.get("artist_name") or "").lower(): a["artist_id"]
                      for a in cache.all_artist_meta().values()}
        for s_row in sim:
            s_row["artist_id"] = name_to_id.get(s_row["name"].lower())

        # The official top-10: BORROWED-TIME live garnish (D-33) — authed only
        # (PKCE = no app token; a guest call would leak the owner's token).
        live_rows: Optional[list[dict]] = None
        live_dark = False
        can_analyze = False
        if auth_web.is_authenticated(session):
            df = _artist_top_cached(artist_id, session)
            if df is None or df.empty:
                live_dark = True
            else:
                recs = df.to_dict("records")
                cache.remember_meta(recs)  # names/art/popularity → worker-searchable
                have = cache.cached_ids([r["spotify_track_id"] for r in recs])
                live_rows = [{"id": r["spotify_track_id"],
                              "name": r.get("track_name"),
                              "popularity": r.get("popularity"),
                              "analyzed": r["spotify_track_id"] in have}
                             for r in recs]
                can_analyze = any(not r["analyzed"] for r in live_rows)

        return templates.TemplateResponse(request, "artist.html", {
            **_viewer_flags(session), "artist": card, "artist_id": artist_id,
            "yours": yours, "similar": sim, **ctx_albums,
            "live_rows": live_rows, "live_dark": live_dark,
            "can_analyze": can_analyze})

    @app.post("/artist/{artist_id}/analyze")
    def artist_analyze(request: Request, artist_id: str):
        """Analyze-on-demand (owner fork, D-33): queue the artist's top tracks.
        Authed ONLY (needs a live token + write intent) — guests never enqueue.
        Server-side re-fetch: the queue set never comes from form data."""
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        if not _ARTIST_ID_RE.fullmatch(artist_id or ""):
            return RedirectResponse("/artists", status_code=303)
        cache = _feature_cache()
        # server-side data (≤10-min TTL cache of our OWN fetch) — never form data
        df = _artist_top_cached(artist_id, session)
        if df is not None and not df.empty:
            recs = df.to_dict("records")[:10]
            cache.remember_meta(recs)
            cache.enqueue([r["spotify_track_id"] for r in recs])  # O1 dedup guard applies
        return RedirectResponse(f"/artist/{artist_id}", status_code=303)

    @app.get("/recommend", response_class=HTMLResponse)
    def recommend_view(request: Request):
        session = request.state.session
        if not _is_viewer(session):
            return RedirectResponse("/", status_code=303)
        ctx = _recommend_context(session, dict(request.query_params))
        if ctx is None:
            return RedirectResponse(
                "/dashboard" if auth_web.is_authenticated(session) else "/", status_code=303)
        return templates.TemplateResponse(request, "recommend.html",
                                          {**ctx, **_viewer_flags(session)})

    @app.get("/explore", response_class=HTMLResponse)
    def explore(request: Request, f: str = "danceability",
                x: str = "tempo", y: str = "energy"):
        session = request.state.session
        if not _is_viewer(session):
            return RedirectResponse("/", status_code=303)
        ctx = _explore_context(session, f, x, y)
        if ctx is None:
            return RedirectResponse(
                "/dashboard" if auth_web.is_authenticated(session) else "/", status_code=303)
        return templates.TemplateResponse(request, "explore.html",
                                          {**ctx, **_viewer_flags(session)})

    _PLAYLIST_ID_RE = re.compile(r"[0-9A-Za-z]{1,64}")  # base62 guard on the import id

    def _user_playlists(client):
        """(me_id, playlists DataFrame, reachable) for the authed client — both
        absent-safe (borrowed-time /me + /me/playlists). me_id None fails the
        membership filter CLOSED (collaborative-only).

        `reachable` is the honesty bit. Both fetches fail closed to None, which
        renders EXACTLY like "you own no importable playlists" — so a Spotify
        429 told the owner a confident falsehood about his own account (his 30
        playlists had not gone anywhere). Rate limiting is likely here now that
        a whole playlist imports at once, and `client_from_session` runs
        retries=0 on purpose (spotipy's default sleeps inside the render — the
        session-36 hang), so a 429 is abrupt by design. The caller needs to be
        able to say "we couldn't ask" instead of "the answer is none"."""
        reachable = True
        try:
            me_id = fetch_user_profile(client).get("user_id")
        except Exception:  # noqa: BLE001
            me_id, reachable = None, False
        try:
            df = fetch_user_playlists(client)
        except Exception:  # noqa: BLE001
            df, reachable = None, False
        return me_id, df, reachable

    @app.get("/playlists", response_class=HTMLResponse)
    def playlists_page(request: Request):
        """Import from YOUR playlists (Epic I). Authed-only (needs a live token);
        if the session's token predates the scope change, render a re-consent CTA
        instead of a broken fetch."""
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        flags = _viewer_flags(session)
        # server-side flash (trusted, built from ints) — NEVER a query param, so a
        # crafted /playlists?msg=<script> can't reach the |safe render.
        msg = session.pop("pl_msg", None)
        base = {**flags, "cap": config.PLAYLIST_IMPORT_CAP, "msg": msg,
                "msg_id": session.pop("pl_msg_id", None),
                "queue_depth": _feature_cache().queue_count()}
        if not auth_web.has_playlist_scope(session):
            return templates.TemplateResponse(request, "playlists.html",
                                              {**base, "needs_consent": True, "cards": []})
        me_id, df, reachable = _user_playlists(auth_web.client_from_session(session))
        cache = _feature_cache()
        cards = playlists_mod.playlist_cards(
            df, me_id, members=cache.playlist_track_ids(),
            analyzed_ids=cache.analyzed_ids(),
            needs_source_ids=cache.dead_lettered_ids(),
            duplicate_of=cache.duplicate_flags(),
            walked=cache.playlist_walks())
        # "Spotify wouldn't answer" and "you own none" are different facts, and
        # only one of them is about the visitor's account.
        return templates.TemplateResponse(request, "playlists.html",
                                          {**base, "needs_consent": False,
                                           "cards": cards, "unreachable": not reachable})

    @app.post("/playlists/{playlist_id}/analyze")
    def playlist_analyze(request: Request, playlist_id: str):
        """Import a playlist's tracks into the library (Epic I). Authed + scope-
        gated + membership-checked (own/collaborative only) BEFORE any fetch — a
        guest/anon or a stranger's playlist never reaches the worker. Server-side
        re-fetch (the id set never comes from form data), capped to a TOTAL by
        slicing before enqueue (the fetcher `limit` is only a page size)."""
        session = request.state.session
        if not auth_web.is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        if not auth_web.has_playlist_scope(session):
            return RedirectResponse("/playlists", status_code=303)  # re-consent CTA
        if not _PLAYLIST_ID_RE.fullmatch(playlist_id or ""):
            return RedirectResponse("/playlists", status_code=303)
        client = auth_web.client_from_session(session)
        me_id, df, reachable = _user_playlists(client)
        if not reachable:
            # The membership gate fails CLOSED, which is right — but saying
            # "that isn't your playlist" when Spotify simply didn't answer
            # accuses the visitor of something untrue.
            session["pl_msg"] = ("Spotify didn't answer just now (usually a rate "
                                 "limit while a big import runs) — nothing was "
                                 "queued. Try again in a minute.")
            return RedirectResponse("/playlists", status_code=303)
        if playlist_id not in playlists_mod.importable_ids(df, me_id):
            session["pl_msg"] = "That playlist isn't one you own or collaborate on."
            return RedirectResponse("/playlists", status_code=303)
        cap = config.PLAYLIST_IMPORT_CAP
        cache = _feature_cache()
        # SKIP-then-CAP (owner report, session 36) walking the playlist PAGE BY
        # PAGE and stopping as soon as `cap` genuinely-new tracks are in hand.
        #
        # Draining the whole playlist first was the actual rate-limit cost: 21
        # sequential API calls for a 1004-track playlist, every click, just to
        # decide which 100 to queue — so the owner's biggest playlist could not
        # be imported at all. Stopping early usually costs 2-3 calls, and the
        # skip-first ordering still walks deeper on every repeat click.
        # RESUME where the last click stopped. We always page from the front, so
        # the ids we've recorded for this playlist are a PREFIX of it — their
        # count is the offset to restart at. Derived from data we already have,
        # so there is no cursor to persist and go stale.
        #
        # Self-correcting: if the playlist SHRANK below what we've seen, tracks
        # were removed and every later offset shifted, so rescan from 0. The
        # cost of being wrong is re-reading pages, never skipping a track.
        known_list = cache.playlist_track_ids().get(playlist_id) or []
        known = set(known_list)
        track_total = playlists_mod.track_count_for(df, playlist_id)
        start_offset = len(known) if (track_total is None
                                      or track_total >= len(known)) else 0
        seen: set[str] = set()
        ids: list[str] = list(known)  # every id known for this playlist
        selected: list[dict] = []     # the new ones we'll queue
        n_skipped = 0
        exhausted = False
        pages_read = 0

        # MEMBERSHIP FIRST, at zero API cost. A track we've already recorded can
        # still be unanalyzed — it failed, or was never queued — and once the
        # resume offset walked past it, paging could never reach it again: 411
        # such tracks were stranded across the owner's playlists while Analyze
        # reported "nothing new to add" (2026-07-27). We hold their ids already,
        # so no fetch is needed to act on them.
        #
        # Dead-lettered ids are EXCLUDED rather than merely skipped by enqueue:
        # they would otherwise consume every cap slot and starve the tracks that
        # can actually be queued (one playlist had 78 of them against a cap of
        # 50). They belong to the needs-source repair queue, and the card says so.
        backlog: list[str] = []
        n_needs_source = 0
        if known_list:
            done_ids = cache.cached_ids(known_list) | cache.active_ids(known_list)
            dead = cache.dead_lettered_ids()
            # A dedup twin has no features of its own because the CANONICAL
            # carries them (O3) — the recording is already in the library, so it
            # is resolved, not pending. `enqueue` would skip it anyway (its job
            # is closed), but leaving it in the backlog would spend a cap slot
            # on work that cannot happen.
            twins = cache.twin_ids()
            # A track with no stored name cannot be searched for — queueing it
            # burns three attempts and dead-letters it as "no track metadata".
            # THE invariant this whole class of bug needed: never enqueue what
            # cannot be looked up. Paging supplies the missing metadata (it now
            # stores every record it reads), so these recover on a later walk
            # rather than being spent.
            searchable = cache.searchable_ids(known_list)
            for tid in known_list:
                if tid in done_ids or tid in twins:
                    continue
                if tid in dead:
                    n_needs_source += 1
                    continue
                if tid not in searchable:
                    continue
                backlog.append(tid)
            backlog = backlog[:cap] if cap > 0 else backlog
            seen.update(backlog)
        fetch_failed = False
        room_left = cap <= 0 or len(backlog) < cap
        try:
            # Skip the network entirely when the backlog already fills the cap —
            # the cheapest import is the one that makes no API call at all.
            for page, is_last in (iter_playlist_track_pages(
                    playlist_id, client, start_offset=start_offset)
                    if room_left else ()):
                pages_read += 1
                # bridge key MUST be a non-empty string (ground rule #1). Drop
                # local/None tracks — pandas turns None into a TRUTHY
                # float('nan'), so the isinstance check is load-bearing.
                uniq = [r for r in page
                        if isinstance(r.get("spotify_track_id"), str)
                        and r["spotify_track_id"]
                        and not (r["spotify_track_id"] in seen
                                 or seen.add(r["spotify_track_id"]))]
                page_ids = [r["spotify_track_id"] for r in uniq]
                ids.extend(page_ids)
                # Store metadata for EVERY track we page over, not just the ones
                # this click queues. Membership recorded all of them, but
                # remember_meta used to see only `selected` — so a track beyond
                # the cap got a membership row with NO name, and the later
                # backlog pass enqueued it with nothing to search on. 200 of
                # #Rock's tracks dead-lettered as "no track metadata for the
                # audio search" that way. We already fetched this; storing it is
                # free and makes membership self-sufficient.
                if uniq:
                    cache.remember_meta(uniq)
                skip = cache.cached_ids(page_ids) | cache.active_ids(page_ids)
                n_skipped += len(skip)
                for r in uniq:
                    if r["spotify_track_id"] in skip:
                        continue
                    selected.append(r)
                    if 0 < cap <= len(backlog) + len(selected):
                        break
                exhausted = is_last
                if 0 < cap <= len(backlog) + len(selected):
                    break
                if pages_read >= config.PLAYLIST_IMPORT_MAX_PAGES:
                    break          # hard API-call ceiling, reliability first
        except Exception:  # noqa: BLE001
            # A failed READ is not an empty playlist (PlaylistFetchError exists
            # to keep those apart). If the backlog gave us work anyway, do it and
            # say the fetch failed — bailing entirely would waste a click that
            # needed no network to be useful.
            fetch_failed = True
            if not backlog:
                session["pl_msg"] = ("Couldn't read that playlist's tracks — Spotify "
                                     "didn't answer (usually a rate limit). Nothing "
                                     "was queued; try again in a minute.")
                return RedirectResponse("/playlists", status_code=303)
        if selected:
            cache.remember_meta(selected)
        # Backlog first: these are already-known ids, so they cost nothing to
        # queue and would otherwise stay unreachable forever.
        queued = cache.enqueue(backlog + [r["spotify_track_id"] for r in selected])
        # Remember WHICH playlist these came from, so /playlists can report
        # "N of M analyzed". We stopped early, so `ids` is a PREFIX of the
        # playlist — merge rather than replace, or each capped click would
        # forget what the previous one learned. Only a walk that reached the end
        # knows the full membership and may replace it.
        cache.remember_playlist_tracks(playlist_id, ids, replace=exhausted)
        # Whether we reached the END. Spotify's track_count includes items the
        # items endpoint never returns as playable tracks (local files,
        # market-unavailable), so a fully-walked playlist can hold fewer members
        # than its advertised count — "Cottage 2.0" read 55 of 57 forever with a
        # button offering to fetch a 57th track that does not exist for us.
        if not fetch_failed:
            cache.mark_playlist_walk(playlist_id, complete=exhausted,
                                     n_found=len(set(ids)))
        session["pl_msg"] = playlists_mod.coverage_line(
            len(queued), n_skipped, 0 if exhausted else None, cap,
            scanned=len(seen), queue_depth=cache.queue_count(),
            needs_source=n_needs_source, fetch_failed=fetch_failed)
        session["pl_msg_id"] = playlist_id      # highlight the card we just acted on
        # Stay on /playlists (owner, 2026-07-27). Landing on /queue was meant to
        # be proof the click worked, but the common case is a playlist whose next
        # tracks are ALREADY analyzed — nothing new to queue — so it dropped the
        # visitor on an empty queue page, which reads as "nothing happened". The
        # confirmation belongs next to the card that was clicked, and it now
        # states what was scanned, what was already done, and what was queued.
        return RedirectResponse("/playlists", status_code=303)

    @app.get("/queue", response_class=HTMLResponse)
    def queue_page(request: Request):
        """The live extraction queue (owner ask, session 36): what's analyzing
        NOW and what's up next, in the worker's true FIFO order, with the honest
        ~50 s/track ETA. PUBLIC — the same posture as /library, which already
        shows every unanalyzed track as 'analyzing…' (D-18 corpus data)."""
        cache = _feature_cache()
        rows = cache.queue_rows()
        # `queue_rows` is display-capped, so len(rows) is the size of the LIST,
        # not of the queue. Deriving n and the ETA from it under-reported a
        # 1000-track import as "200 tracks · 167 min" — now that a whole playlist
        # can land at once, that gap is the difference between 3 hours and a day.
        n = cache.queue_count()
        eta_min = max(1, round(n * _SECONDS_PER_TRACK / 60)) if n else 0
        session = request.state.session
        return templates.TemplateResponse(request, "queue.html", {
            **_viewer_flags(session),
            "rows": rows, "n": n, "shown": len(rows), "eta_min": eta_min,
            "sec_per_track": _SECONDS_PER_TRACK,
            # the post-import confirmation, carried over from /playlists
            "msg": session.pop("pl_msg", None),
        })

    @app.get("/library", response_class=HTMLResponse)
    def library_page(request: Request):
        """The H1 catalog — PUBLIC corpus data (D-18): every track in the app,
        searchable/sortable, with the honest analyzed-vs-known coverage. Renders
        for anyone (no login, no guest); the 'My songs' tab overlays a viewer's
        own analyzed set. Population-only by design, so no builder refactor."""
        session = request.state.session
        params = dict(request.query_params)
        cache = _feature_cache()
        # O3c: one row per RECORDING by default; ?dupes=all expands the twins
        expand_dupes = params.get("dupes") == "all"
        rows = library_view_mod.consolidate_rows(
            library_view_mod.annotate_queue_state(
                library_view_mod.annotate_dupes(cache.library_rows()),
                cache.job_states()),
            expand=expand_dupes)
        # D-56: the owner's repair queue — acquisition failures awaiting a
        # pasted link / uploaded file. Owner-only (ops data, fail-closed).
        ns_reasons: dict[str, str] = {}
        owner = _is_owner(session)
        if owner and params.get("filter") == "needs-source":
            ns_reasons = _needs_source(cache)
            rows = [r for r in rows if r["id"] in ns_reasons]
        q = (params.get("q") or "").strip()
        sort = params.get("sort") or "name"
        order = params.get("order") or "asc"
        tab = params.get("tab") if params.get("tab") in ("all", "mine", "playlists") else "all"
        flags = _viewer_flags(session)
        # a viewer's own analyzed set (guest = the demo persona's taste)
        my_ids = {t for ids in ((session.get("taste") or {}).get("range_ids") or {}).values()
                  for t in ids}
        my_count = sum(1 for r in rows if r["id"] in my_ids) if flags["viewer"] else 0
        # anon / non-viewer can't land on a personal tab
        if tab in ("mine", "playlists") and not flags["viewer"]:
            tab = "all"
        if tab == "playlists" and not flags["authed"]:
            tab = "mine"
        mine = my_ids if tab == "mine" else None
        v = library_view_mod.library_view(rows, q=q, sort=sort, order=order, mine_ids=mine)
        # Filter and sort ran over the WHOLE corpus above; this only slices the
        # result. `shown`, `total` and `analyzed` keep their meanings — the page
        # never shrinks the coverage claim, it only says which slice is visible.
        v = library_view_mod.page_slice(v, page=params.get("page"),
                                        per=params.get("per"))
        ctx: dict[str, Any] = {
            **flags, "tab": tab, "q": q, "sort": v["sort"], "order": v["order"],
            "sort_options": library_view_mod.sort_options(),
            "rows": v["page_rows"], "shown": v["shown"], "total": v["total"],
            "analyzed": v["analyzed"], "my_count": my_count,
            "page": v["page"], "pages": v["pages"], "per": v["per"],
            "is_all": v["is_all"], "from_index": v["from_index"],
            "to_index": v["to_index"], "page_sizes": v["page_sizes"],
            "pager": library_view_mod.page_links(params, v),
            "all_url": "/library?" + library_view_mod.pager_query(params, per="all",
                                                                  page=None),
            "carry": {k: params.get(k) for k in ("filter", "dupes")
                      if params.get(k)},
            # D-56: owner-only repair-queue affordances
            "is_owner": owner, "ns_reasons": ns_reasons,
            "ns_filtered": bool(ns_reasons),
            "ns_count": len(_needs_source(cache)) if owner else 0,
        }
        if tab == "mine":
            # v["rows"] is the FULL matching set — page_slice preserves it and
            # puts the visible slice in page_rows. Counting page_rows here would
            # make the "why only N analyzed" explainer describe one page and
            # under-report the visitor's own library.
            mine_analyzed = sum(1 for r in v["rows"] if r["analyzed"])
            ctx["why_n"] = library_view_mod.why_n_analyzed(mine_analyzed, _TOP_LIMIT)
        return templates.TemplateResponse(request, "library.html", ctx)

    @app.get("/song/{track_id}", response_class=HTMLResponse)
    def song(request: Request, track_id: str):
        # PUBLIC deep-dive (D-18): a track's features are corpus data. `viewer`
        # flags stay false for anon (nav renders the public shape). Id is base62-
        # guarded; the cache read is parameterized and _spectrogram_path is
        # traversal-safe, so widening the audience adds no new attack surface.
        session = request.state.session
        if not _TRACK_ID_RE.fullmatch(track_id or ""):
            return RedirectResponse("/library", status_code=303)
        cache = _feature_cache()
        features = cache.get([track_id]).get(track_id)
        meta = cache.get_meta(track_id) or {}
        ctx: dict[str, Any] = {
            **_viewer_flags(session), "track_id": track_id,
            "name": meta.get("track_name") or track_id,
            "artist": meta.get("artist_names") or "",
            # F5: there was NO path from a song to its artist anywhere in the
            # app. The id is already stored on the meta row (97% coverage).
            "primary_artist_id": meta.get("primary_artist_id"),
            "analyzed": features is not None,
            # Q2/D-51: where this track's audio came from. None until the Q3
            # backfill (the honest ∅ tier). youtube_title/channel are UNTRUSTED
            # external strings — the template renders them WITHOUT |safe so
            # Jinja auto-escapes (the |safe SVG XSS lesson, security review).
            "provenance": cache.provenance_for(track_id),
        }
        # Owner call (2026-07-23): features whose SOURCE isn't recorded are not
        # presented at all. They came from the pre-provenance matcher — the same
        # one that produced wrong songs and DJ sets — so showing tempo/energy as
        # fact invites trust the data hasn't earned. A repair reveals them.
        ctx["source_validated"] = ctx["provenance"] is not None
        # O3c: a twin's page keeps working (public URLs never break) but names
        # its canonical — the features/provenance shown are THIS release's own.
        canon_id = cache.duplicate_flags().get(track_id)
        if canon_id:
            cmeta = cache.get_meta(canon_id) or {}
            ctx["canonical"] = {"id": canon_id,
                                "name": cmeta.get("track_name") or canon_id}
        # D-56: the owner sees the repair tools + this track's queue reason;
        # the flash is server-built (never a query param — the |safe lesson).
        ctx["is_owner"] = _is_owner(session)
        if ctx["is_owner"]:
            ctx["repair_msg"] = session.pop("repair_msg", None)
            ctx["needs_source_reason"] = _needs_source(cache, track_id)
            from ..store.repair import MAX_UPLOAD_BYTES, find_owner_audio
            ctx["has_owner_audio"] = find_owner_audio(
                _OWNER_AUDIO_DIR, track_id) is not None
            ctx["max_upload_mb"] = MAX_UPLOAD_BYTES // (1024 * 1024)
        if features is not None and ctx["source_validated"]:
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

    @app.get("/song/{track_id}/features", response_class=HTMLResponse)
    def song_features(request: Request, track_id: str):
        """D-66: ALL 83 stored features for one track, not just the highlights.

        Same posture as /song — PUBLIC (corpus data, D-18), base62-guarded, and
        subject to the SAME D-57 withhold: a track whose source isn't recorded
        shows nothing here either. Presenting 83 numbers as fact would be a
        bigger version of exactly the trust the withhold exists to protect.

        A POINT LOOKUP, deliberately: the 82-col dict is read for ONE track
        (`cache.get([id])`), while every corpus-wide number comes from the
        marts. Nothing here iterates the corpus (the journal-#56 rule).
        """
        session = request.state.session
        if not _TRACK_ID_RE.fullmatch(track_id or ""):
            return RedirectResponse("/library", status_code=303)
        cache = _feature_cache()
        features = cache.get([track_id]).get(track_id)
        meta = cache.get_meta(track_id) or {}
        provenance = cache.provenance_for(track_id)
        ctx: dict[str, Any] = {
            **_viewer_flags(session), "track_id": track_id,
            "name": meta.get("track_name") or track_id,
            "artist": meta.get("artist_names") or "",
            # F5: there was NO path from a song to its artist anywhere in the
            # app. The id is already stored on the meta row (97% coverage).
            "primary_artist_id": meta.get("primary_artist_id"),
            "analyzed": features is not None,
            "source_validated": provenance is not None,
            "detail": None, "promoted": list(RAW_FEATURE_PROMOTED),
        }
        if features is not None and ctx["source_validated"]:
            dictionary = load_raw_feature_dictionary()
            stats = load_raw_feature_stats()
            if dictionary is not None and stats is not None:
                ctx["detail"] = build_feature_detail(
                    features, dictionary.to_dict("records"), stats.to_dict("records"))
        return templates.TemplateResponse(request, "song_features.html", ctx)

    @app.get("/audio/{track_id}")
    def owner_audio(request: Request, track_id: str):
        """V2: stream a RETAINED owner upload so it can be played back and
        verified. OWNER-ONLY by deliberate choice — a YouTube-sourced track is
        verifiable via its public link (YouTube hosts it, we only link), but an
        uploaded file is hosted by US, and serving full copyrighted audio to
        the public is a licensing exposure this project won't take. Visitors
        still get the spectrogram + the honest 'owner-supplied' label."""
        if not _TRACK_ID_RE.fullmatch(track_id or ""):
            return RedirectResponse("/library", status_code=303)
        if not _is_owner(request.state.session):
            return RedirectResponse(f"/song/{track_id}", status_code=303)
        from ..store.repair import find_owner_audio
        path = find_owner_audio(_OWNER_AUDIO_DIR, track_id)
        if path is None:
            return HTMLResponse("no retained audio for this track", status_code=404)
        return FileResponse(path)

    @app.post("/song/{track_id}/repair-link")
    def song_repair_link(request: Request, track_id: str, url: str = Form("")):
        """D-56: owner pastes the correct YouTube link. The engine still runs
        the full validation (host allowlist, duration HARD-REJECT, DSP swap)."""
        session = request.state.session
        if not _TRACK_ID_RE.fullmatch(track_id or ""):
            return RedirectResponse("/library", status_code=303)
        if not _is_owner(session):
            return RedirectResponse(f"/song/{track_id}", status_code=303)
        from ..store.repair import repair_from_link
        ok, msg = repair_from_link(_feature_cache(), track_id, url,
                                   audio_dir=_REPAIR_AUDIO_DIR,
                                   spectrogram_dir=_SPECTROGRAM_DIR,
                                   marts_dir=_MARTS_DIR)
        session["repair_msg"] = ("✓ " if ok else "✗ ") + msg
        return RedirectResponse(f"/song/{track_id}", status_code=303)

    @app.post("/song/{track_id}/repair-upload")
    def song_repair_upload(request: Request, track_id: str,
                           file: UploadFile = _UPLOAD_FILE):
        """D-56: owner uploads the track's audio (for songs not on YouTube —
        the Roots-by-WILDS case). Magic-byte sniff, streamed size cap, and the
        duration HARD-REJECT all still apply."""
        session = request.state.session
        if not _TRACK_ID_RE.fullmatch(track_id or ""):
            return RedirectResponse("/library", status_code=303)
        if not _is_owner(session):
            return RedirectResponse(f"/song/{track_id}", status_code=303)
        from ..store.repair import repair_from_upload
        ok, msg = repair_from_upload(_feature_cache(), track_id, file.file,
                                     audio_dir=_REPAIR_AUDIO_DIR,
                                     spectrogram_dir=_SPECTROGRAM_DIR,
                                     keep_dir=_OWNER_AUDIO_DIR,
                                     marts_dir=_MARTS_DIR)
        session["repair_msg"] = ("✓ " if ok else "✗ ") + msg
        return RedirectResponse(f"/song/{track_id}", status_code=303)

    @app.get("/spectrogram/{track_id}")
    def spectrogram(request: Request, track_id: str):
        # PUBLIC (D-18): the mel-spectrogram is corpus display data, and /library
        # already reveals which tracks are analyzed, so the old 200-vs-404
        # enumeration-oracle concern is moot. _spectrogram_path is traversal-safe.
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
            "scopes": config.SCOPES.split(),  # single source — copy can't drift from the gate
        })

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
