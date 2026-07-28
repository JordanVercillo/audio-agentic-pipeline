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
    assert "100" in line and "<b>40</b> were already done" in line
    assert "24" in line and "cap" in line
    clean = playlists.coverage_line(queued=12, skipped=0, remaining=0, cap=100)
    assert "12" in clean and "already done" not in clean and "cap" not in clean


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
        self.playlist_members: dict = {}

    def remember_playlist_tracks(self, playlist_id, track_ids, *, replace=False):
        # mirrors the real merge-unless-complete semantics
        prev = [] if replace else self.playlist_members.get(playlist_id, [])
        merged = list(dict.fromkeys([*prev, *track_ids]))
        self.playlist_members[playlist_id] = merged
        return len(merged)

    def playlist_track_ids(self):
        return dict(self.playlist_members)

    def analyzed_ids(self):
        return set(self.cached)

    def cached_ids(self, ids):
        return {i for i in ids if i in self.cached}

    def active_ids(self, ids):
        return {i for i in ids if i in self.active}

    def remember_meta(self, recs):
        self.remembered = recs

    def enqueue(self, ids):
        self.enqueued = ids
        return list(ids)

    def queue_count(self):
        return len(self.enqueued) + len(self.active)

    dead: set = frozenset()
    twins: set = frozenset()

    def dead_lettered_ids(self):
        return set(self.dead)

    def twin_ids(self):
        return set(self.twins)

    def duplicate_flags(self):
        return {t: "canon" for t in self.twins}


def _mock_membership(monkeypatch):
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", lambda c: {"user_id": "me"})
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", lambda c: _PL_DF)


def _big_playlist(monkeypatch, n=2000):
    """A big playlist served page by page (the route pages now, it never drains)."""
    def _iter(pid, sp=None, limit=50, start_offset=0):
        off = start_offset
        while off < n:
            yield ([{"spotify_track_id": f"t{i}", "track_name": f"S{i}",
                     "artist_names": "A"}
                    for i in range(off, min(off + 50, n))], off + 50 >= n)
            off += 50
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages", _iter)
    return _FakeCache(cached={f"t{i}" for i in range(30)},      # first 30 analyzed
                      active={f"t{i}" for i in range(30, 50)})  # next 20 already queued


def test_analyze_stays_on_playlists_and_skips_before_it_caps(client, monkeypatch):
    """Analyze returns to /playlists (owner, 2026-07-27). Landing on /queue was
    meant to prove the click worked, but the common case is a playlist whose next
    tracks are ALREADY analyzed — nothing new to queue — so it dropped the
    visitor on an empty queue page, which reads as "nothing happened".

    Skip-then-cap (session 36) still holds — the 50 already analyzed/queued are
    passed over before the cap is spent, so a repeat click walks deeper."""
    _mock_membership(monkeypatch)
    fake = _big_playlist(monkeypatch)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 100)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/playlists"
    assert fake.enqueued == [f"t{i}" for i in range(50, 150)]     # skip → then cap


def test_cap_zero_still_takes_everything_it_reads(client, monkeypatch):
    """The cap is configurable, not mandatory: 0 means "don't stop for a cap".
    The page ceiling still bounds the API cost, which is the reliability floor."""
    _mock_membership(monkeypatch)
    fake = _big_playlist(monkeypatch, n=120)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 0)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == [f"t{i}" for i in range(50, 120)]


def test_analyze_excludes_local_and_none_ids(client, monkeypatch):
    _mock_membership(monkeypatch)
    mixed = pd.DataFrame([
        {"spotify_track_id": "good1", "track_name": "A", "artist_names": "X"},
        {"spotify_track_id": None, "track_name": "local", "artist_names": "X"},
        {"spotify_track_id": "good2", "track_name": "B", "artist_names": "X"},
    ])
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages",
                        lambda pid, sp=None, limit=50, start_offset=0:
                        iter([(mixed.to_dict("records"), True)]))
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == ["good1", "good2"]  # the None row dropped


def test_analyze_rejects_non_member_playlist(client, monkeypatch):
    _mock_membership(monkeypatch)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not fetch a stranger's playlist")))
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


# ── a failed fetch is not an empty account (owner report, 2026-07-25) ────────
def _rate_limited(*a, **k):
    from spotipy.exceptions import SpotifyException
    raise SpotifyException(429, -1, "rate/request limit")


def test_rate_limited_playlists_page_says_so_instead_of_claiming_none(client, monkeypatch):
    """THE bug the owner hit: 30 playlists vanished and the page said "No
    importable playlists found" — a confident claim about his Spotify account
    when the truth was a 429. Both fetches fail closed to None, which renders
    identically to owning nothing.

    Rate limits are now LIKELY (a whole playlist imports at once, and
    client_from_session runs retries=0 because spotipy's default sleeps inside
    the render — the session-36 hang), so this state needs its own words."""
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", _rate_limited)
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", _rate_limited)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.get("/playlists")
    assert r.status_code == 200
    assert "didn't answer" in r.text and "temporary" in r.text
    assert "Try again" in r.text
    # ...and it must NOT make the false claim
    assert "No importable playlists found" not in r.text


def test_a_genuinely_empty_account_still_says_none(client, monkeypatch):
    """The inverse — the honest empty state must survive. If both messages
    collapsed into one, the fix would just be a different lie."""
    import pandas as _pd
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", lambda c: {"user_id": "me"})
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", lambda c: _pd.DataFrame())
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.get("/playlists")
    assert "No importable playlists found" in r.text
    assert "didn't answer" not in r.text


def test_rate_limited_analyze_does_not_accuse_you_of_not_owning_it(client, monkeypatch):
    """The membership gate fails CLOSED, which is correct — but "that isn't your
    playlist" is an accusation, and a 429 hasn't earned it."""
    monkeypatch.setattr("src.webapp.app.fetch_user_profile", _rate_limited)
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", _rate_limited)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/playlists"
    assert fake.enqueued == []                      # nothing queued, correctly
    body = client.get("/playlists").text
    assert "didn't answer" in body and "isn't one you own" not in body


def test_a_failed_TRACK_fetch_says_so_instead_of_queued_zero(client, monkeypatch):
    """`tdf = None` used to fall through to "Queued 0 new tracks", which reads as
    "there was nothing new" rather than "we never got the list"."""
    _mock_membership(monkeypatch)
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages", _rate_limited)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    body = client.get("/playlists").text
    assert "Couldn't read that playlist's tracks" in body
    assert "Queued <b>0</b>" not in body
    assert fake.enqueued == []


# ── capped, resumable import (owner, 2026-07-25: reliability over speed) ─────
def _paged(monkeypatch, n=1004, page_size=50):
    """A big playlist served page by page, recording the offsets requested — the
    API cost is the thing under test, so we count the calls.

    Also re-points the /me/playlists frame so `track_count` MATCHES the pages
    served: the route compares the two to detect a playlist that shrank, and a
    fixture where they disagree is testing the wrong thing."""
    calls: list[int] = []

    def _iter(pid, sp=None, limit=50, start_offset=0):
        calls.append(start_offset)
        off = start_offset
        while off < n:
            page = [{"spotify_track_id": f"t{i}", "track_name": f"S{i}",
                     "artist_names": "A"} for i in range(off, min(off + page_size, n))]
            off += page_size
            yield page, off >= n
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages", _iter)
    df = _PL_DF.copy()
    df.loc[df["playlist_id"] == "mine1", "track_count"] = n
    monkeypatch.setattr("src.webapp.app.fetch_user_playlists", lambda c: df)
    return calls


def test_a_1000_track_playlist_imports_a_capped_slice_without_draining_it(
        client, monkeypatch):
    """The owner's #Rock playlist (1004 tracks) could not be imported at all: the
    route drained EVERY page (21 sequential API calls) just to decide which 100
    to queue, and Spotify rate-limited it. One click now queues `cap` new tracks
    and stops paging."""
    _mock_membership(monkeypatch)
    _paged(monkeypatch)
    fake = _FakeCache()
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 50)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    r = client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/playlists"
    assert fake.enqueued == [f"t{i}" for i in range(50)]      # exactly the cap
    # membership recorded is a PREFIX, not the whole playlist
    assert 0 < len(fake.playlist_members["mine1"]) < 1004


def test_the_next_click_resumes_instead_of_re_reading_the_prefix(client, monkeypatch):
    """Without resume, click N re-pages everything already analyzed before it
    finds anything new — which is the rate limit coming straight back on a big
    playlist. The offset is derived from recorded membership, so no cursor can
    go stale."""
    _mock_membership(monkeypatch)
    calls = _paged(monkeypatch)
    # The 300 recorded members are ANALYZED, so the zero-fetch backlog is empty
    # and this exercises the paging path it is here to test. (A backlog that can
    # satisfy the cap is deliberately served first — see the backlog tests.)
    fake = _FakeCache(cached={f"t{i}" for i in range(300)})
    fake.playlist_members["mine1"] = [f"t{i}" for i in range(300)]   # 6 pages done
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 50)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert calls == [300], f"expected a resume at 300, paged from {calls}"
    assert fake.enqueued == [f"t{i}" for i in range(300, 350)]


def test_a_shrunken_playlist_rescans_from_the_start(client, monkeypatch):
    """If tracks were REMOVED upstream every later offset shifted, so a resume
    would skip songs. Cheaper to re-read pages than to lose a track."""
    _mock_membership(monkeypatch)
    calls = _paged(monkeypatch, n=20)      # playlist now holds 20…
    fake = _FakeCache()
    fake.playlist_members["mine1"] = [f"t{i}" for i in range(40)]    # …we recorded 40
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert calls == [0], "a shrunken playlist must rescan from 0"


def test_the_page_ceiling_bounds_api_calls_even_when_nothing_is_new(
        client, monkeypatch):
    """A click that finds only already-known tracks must still STOP. Without the
    ceiling it would page to the end of a 1000-track playlist hunting for
    something new — the exact cost we removed."""
    _mock_membership(monkeypatch)
    pages_yielded = {"n": 0}

    def _iter(pid, sp=None, limit=50, start_offset=0):
        off = start_offset
        while off < 5000:
            pages_yielded["n"] += 1
            yield ([{"spotify_track_id": f"t{i}", "track_name": "S",
                     "artist_names": "A"} for i in range(off, off + 50)], False)
            off += 50
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages", _iter)
    fake = _FakeCache(cached={f"t{i}" for i in range(5000)})   # everything analyzed
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert pages_yielded["n"] <= config.PLAYLIST_IMPORT_MAX_PAGES
    assert fake.enqueued == []


def test_a_partial_walk_never_claims_the_playlist_is_finished():
    """"0 remaining" on a partial walk would tell the visitor a 1004-track
    playlist was done after 50. Unknown is its own state."""
    # Assert the INVARIANT (does it invite another click?), not the exact
    # wording — the copy is allowed to change, the honesty is not.
    partial = playlists.coverage_line(queued=50, skipped=0, remaining=None, cap=50)
    assert "picks up where it left off" in partial
    partial_none = playlists.coverage_line(queued=0, skipped=50, remaining=None,
                                           cap=50, scanned=50)
    assert "may be more" in partial_none
    complete = playlists.coverage_line(queued=7, skipped=3, remaining=0, cap=50)
    assert "picks up where it left off" not in complete and "may be more" not in complete


def test_card_denominator_is_spotifys_count_not_what_we_have_read():
    """A capped import knows only a prefix; counting members as the denominator
    would shrink a 1004-track playlist to however much we'd read."""
    cards = playlists.playlist_cards(
        _PL_DF, me_id="me",
        members={"mine1": ["a", "b", "c"]}, analyzed_ids={"a", "b"})
    card = next(c for c in cards if c["id"] == "mine1")
    assert card["n_known"] == 40 and card["n_analyzed"] == 2   # 40 = Spotify's count
    other = next(c for c in cards if c["id"] == "collab1")
    assert other["n_known"] is None                            # never imported


# ── the confirmation must make a working click LOOK like one (2026-07-27) ────
def test_nothing_new_reads_as_success_not_a_no_op():
    """Owner: "when I click analyze next 50 it just goes to the queue but I
    don't see any tracks getting extracted." The common case on a well-imported
    library is queued=0 with a large `skipped` — the playlist's next tracks were
    already analyzed. That is a SUCCESS, but "queued 0" plus an empty queue page
    reads as a broken button. `scanned` anchors it."""
    line = playlists.coverage_line(queued=0, skipped=50, remaining=None, cap=50,
                                   scanned=50)
    assert "Checked <b>50</b>" in line
    assert "already analyzed" in line and "nothing new to add" in line
    assert "picks up where it left off" in line       # there IS more to do


def test_a_real_import_says_what_was_queued_and_what_was_already_done():
    line = playlists.coverage_line(queued=30, skipped=20, remaining=None, cap=50,
                                   scanned=50, queue_depth=30)
    assert "Checked <b>50</b>" in line
    assert "queued <b>30</b>" in line and "<b>20</b> were already done" in line
    # the "is it working?" answer, with the queue as evidence
    assert "analyzing them now" in line and 'href="/queue"' in line and "min" in line


def test_the_confirmation_is_shown_on_the_playlists_page(client, monkeypatch):
    """The message belongs next to the card that was clicked — that is the whole
    point of not bouncing to /queue."""
    _mock_membership(monkeypatch)
    fake = _big_playlist(monkeypatch)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 50)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    body = client.get("/playlists").text
    assert "pl-flash" in body and "Checked" in body
    assert "is-acted" in body, "the acted-on card is not highlighted"


def test_the_flash_is_consumed_once(client, monkeypatch):
    """A stale confirmation on a later visit would claim work that isn't
    happening — the same class of lie as "analyzing…" on an empty queue."""
    _mock_membership(monkeypatch)
    fake = _big_playlist(monkeypatch)
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert "pl-flash" in client.get("/playlists").text
    assert "pl-flash" not in client.get("/playlists").text     # gone on reload


# ── the backlog: known-but-unqueued tracks the resume walked past ────────────
def test_known_but_unqueued_tracks_are_reachable_without_any_fetch(client, monkeypatch):
    """Owner: "the playlist doesn't show all the songs as analyzed if there's
    nothing new". A recorded track can still be unanalyzed — it failed, or was
    never queued — and once the resume offset walked past it, paging could never
    reach it again. 411 such tracks were stranded across the owner's playlists
    while Analyze reported "nothing new to add". We hold their ids, so acting on
    them needs no API call at all."""
    _mock_membership(monkeypatch)

    def _never(*a, **k):
        raise AssertionError("the backlog must cost ZERO fetches")
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages", _never)
    fake = _FakeCache(cached={"m0", "m1"})
    fake.playlist_members["mine1"] = ["m0", "m1", "m2", "m3"]   # m2/m3 stranded
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 2)  # backlog fills it → no paging
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == ["m2", "m3"], "the stranded tracks were not queued"


def test_dead_lettered_members_never_eat_the_cap(client, monkeypatch):
    """One playlist held 78 dead-lettered tracks against a cap of 50. Merely
    letting `enqueue` skip them would spend every slot on tracks that cannot be
    queued and starve the ones that can."""
    _mock_membership(monkeypatch)
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages",
                        lambda *a, **k: iter([([], True)]))
    fake = _FakeCache()
    fake.playlist_members["mine1"] = [f"d{i}" for i in range(60)] + ["live1"]
    fake.dead = {f"d{i}" for i in range(60)}
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 50)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == ["live1"], "dead-lettered tracks consumed the cap"
    assert "need a source" in client.get("/playlists").text


def test_the_card_accounts_for_tracks_that_need_a_source():
    """"50 of 129 analyzed" beside "nothing new to add" looked broken. The 78
    that need a MANUAL source are now counted separately, so the shortfall is
    explained rather than mysterious — and the card reads DONE when everything
    fetchable is fetched."""
    cards = playlists.playlist_cards(
        _PL_DF, me_id="me", members={"mine1": [f"t{i}" for i in range(40)]},
        analyzed_ids={f"t{i}" for i in range(10)},
        needs_source_ids={f"t{i}" for i in range(10, 40)})
    card = next(c for c in cards if c["id"] == "mine1")
    assert card["n_analyzed"] == 10 and card["n_needs_source"] == 30
    assert card["n_analyzed"] + card["n_needs_source"] == card["n_known"]


def test_coverage_line_explains_the_needs_source_shortfall():
    line = playlists.coverage_line(queued=0, skipped=0, remaining=None, cap=50,
                                   scanned=0, needs_source=78)
    assert "78" in line and "need a source" in line
    assert "filter=needs-source" in line
    # and it must NOT tell you to click again — clicking cannot fix these
    assert "picks up where it left off" not in line


def test_a_dedup_twin_counts_as_covered_not_missing():
    """Validation finding (2026-07-27): "Anna setlist" read 3 of 7 analyzed while
    all seven RECORDINGS were in the library — the other four were dedup twins,
    which hold no features of their own because the canonical carries them (O3).
    Counting only analyzed_ids reported them missing forever, and no Analyze
    click could ever change the number. 130 members corpus-wide were affected."""
    cards = playlists.playlist_cards(
        _PL_DF, me_id="me",
        members={"mine1": ["real1", "twin1", "twin2", "orphan"]},
        analyzed_ids={"real1", "canon1"},
        duplicate_of={"twin1": "canon1", "twin2": "canon_unanalyzed"})
    card = next(c for c in cards if c["id"] == "mine1")
    # real1 analyzed + twin1 whose canonical IS analyzed = 2 covered.
    # twin2's canonical is NOT analyzed, so it stays honestly uncovered.
    assert card["n_analyzed"] == 2


def test_twins_do_not_consume_cap_slots(client, monkeypatch):
    """`enqueue` would skip a twin anyway (its job is closed), but leaving it in
    the backlog spends a cap slot on work that cannot happen."""
    _mock_membership(monkeypatch)
    monkeypatch.setattr("src.webapp.app.iter_playlist_track_pages",
                        lambda *a, **k: iter([([], True)]))
    fake = _FakeCache()
    fake.playlist_members["mine1"] = ["tw1", "tw2", "real"]
    fake.twins = {"tw1", "tw2"}
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: fake)
    monkeypatch.setattr(config, "PLAYLIST_IMPORT_CAP", 2)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(scope=config.SCOPES))
    client.post("/playlists/mine1/analyze", follow_redirects=False)
    assert fake.enqueued == ["real"], "a twin took a cap slot"
