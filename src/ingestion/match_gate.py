"""
match_gate.py — the ONE acceptance policy for acquired audio (QA2 / B1).

Who may become a track's audio. The matcher (`audio_downloader`) RANKS
candidates; this module decides which are admissible at all. Split that way
because ranking without rejecting is precisely how the corpus got polluted:
heuristic-v1 always returns its least-bad candidate, so for an obscure track
"the best of five wrong answers" wins.

Two bars, one gate:

* ``implausible_duration`` / ``title_affinity`` — the ORIGINAL Q3 guards
  (2026-07-23). Kept verbatim: `repair.py` and `quarantine_wrong_songs.py`
  depend on their exact semantics, and the quarantine decision that removed 27
  wrong songs is only reproducible if the function that made it is unchanged.
* ``confident_match`` — the STRICTER auto-accept bar this module adds. The Q3
  guards still admitted wrong songs; measured over the 72-track needs-source
  queue (2026-07-23, session 57), 4 of 11 candidates that passed them were
  wrong. All four are rejected here.

The four measured failures, and the rule each one forced:

===========================  ============================  ======================
wanted                       matched (wrongly)             rule that now rejects
===========================  ============================  ======================
'Up & Down' — Sammy Virji    'Spice Up My Life'            title CONTAINMENT —
                                                           affinity fired on the
                                                           single token "up"
'I need to know' — D. Reed   'I never had'                 same; the token was "i"
'Alone' — MPH                'Calvin Harris - I'm Not      LEADING-ARTIST — MPH is
                             Alone (MPH Remix)'            the remixer, not the
                                                           performer
'Fly Away XTC' — KETTAMA     '…(Ableton Remake)'  Δ1s      REPRODUCTION markers
===========================  ============================  ======================

Design notes
------------
* **Two-sided duration.** The Q3 guard only rejects audio that is too LONG (it
  was built against DJ sets), so an 83 s "Logic Pro Remake" of a 182 s track
  sailed through. Auto-accept needs both sides.
* **Containment, not token overlap.** A single shared common word is not
  evidence. The track's CORE title (version suffixes and feat-parentheticals
  removed — Spotify's "Name - Radio Edit" convention) must appear in the
  candidate's title.
* **Leading artist.** When a candidate title carries an "Artist - Title"
  separator, only the segment BEFORE it identifies the performer; our artist
  appearing later is usually a remix credit on someone else's song. Without a
  separator we have no leading segment, so the whole title is fair game.
* **Unknown is never a pass.** Missing duration, missing title, missing artist
  → not confident. Never guess (the D-57 posture: no data beats wrong data).

Pure — no network, no I/O, no DB. Unit-tested against the real live pairs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# ── the original Q3 guards (semantics frozen — see the module docstring) ──────

# WRONG-VERSION GUARD (live finding, 2026-07-23 — the first full-run batch).
# heuristic-v1 never rejects, only ranks: when every YouTube candidate for an
# obscure track is a DJ SET, it returns the least-bad one. 19 corpus tracks
# carried mix-length audio that way (up to 37x — a 130-min set stored as a
# 3.5-min track). Fails safe: unknown either side → not implausible.
_DURATION_MAX_RATIO = 2.0     # a remix/extended take may legitimately run longer…
_DURATION_MAX_EXTRA_S = 120.0  # …but not >2x AND >2 min beyond the known length

_AFFINITY_STOPWORDS = frozenset(
    "official audio video music lyric lyrics visualizer hd hq the a an of and "
    "x feat ft featuring remix mix mixed edit vip version".split())


def _tokens(s: Optional[str]) -> set[str]:
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    words = set(re.sub(r"[^a-z0-9]+", " ", t).split())
    return {w for w in words if w not in _AFFINITY_STOPWORDS}


def _squash(s: Optional[str]) -> str:
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", t)


# No SINGLE released track runs this long — an acquisition beyond it is a
# full album / DJ set / podcast, even when we have no per-track ground truth to
# compare against. The live finding (D-59, 2026-07-24): Taylor Swift's "TTPD"
# came in at 7300 s (2 h) because Spotify's duration_ms was 0/missing, so the
# ratio guard below could not fire — "unknown → never guess" quietly admitted a
# 2-hour album as a 4-minute song. 30 min is generously past prog epics and most
# classical single movements; a legit longer piece with a missing Spotify length
# reasonably routes to manual repair rather than auto-accepting silently.
_ABSOLUTE_MAX_TRACK_S = 1800.0


def implausible_duration(actual_s: Optional[float],
                         expected_s: Optional[float]) -> bool:
    """True when acquired audio is far too long to be this track (a DJ set /
    full-album upload).

    ONE-SIDED by design — this is the post-download backstop, and audio that is
    too SHORT is caught by `duration_mismatch` at the auto-accept gate.

    With a known Spotify length, "far too long" is relative to it. WITHOUT one
    (missing/zero duration_ms), we still reject audio longer than any plausible
    single track — the only case where "never guess" was wrong, because a 2-hour
    file is not a 4-minute song regardless of what we don't know (D-59)."""
    if not actual_s or actual_s <= 0:
        return False
    if not expected_s or expected_s <= 0:
        return actual_s > _ABSOLUTE_MAX_TRACK_S
    return actual_s > max(_DURATION_MAX_RATIO * expected_s,
                          expected_s + _DURATION_MAX_EXTRA_S)


def title_affinity(track_name: Optional[str], artist: Optional[str],
                   youtube_title: Optional[str], channel: Optional[str] = None,
                   ) -> bool:
    """True when the candidate plausibly IS this song: at least one meaningful
    TITLE token appears in the video title/channel, or the space-squashed
    titles contain each other ("Airmaxes" vs "Air Maxes" — the tokenization
    artifact). Artist-only overlap is NOT enough — a same-artist different
    song ("305 LUV STORY" ← Gonzy's SOBREDOSIS) must reject to manual.

    The WEAK bar: it clears obvious mismatches but a single shared common word
    passes it. `confident_match` is the bar for admitting audio unattended."""
    title_toks = _tokens(track_name)
    yt_toks = _tokens(youtube_title) | _tokens(channel)
    if title_toks & yt_toks:
        return True
    squash_t = _squash(track_name)
    squash_y = _squash(youtube_title)
    return bool(squash_t) and bool(squash_y) and (
        squash_t in squash_y or squash_y in squash_t)


# ── the strict auto-accept bar (QA2) ─────────────────────────────────────────

# A re-creation is not the recording. These are production-tutorial and
# karaoke markers — high precision on purpose: "remix"/"bootleg"/"edit" are
# NOT here, because remixes are legitimate corpus members (the S2 sign-off:
# a blanket remix penalty would gut the electronic genre).
_REPRODUCTION_MARKERS = (
    "remake", "ableton", "fl studio", " flp", "logic pro", "tutorial",
    "how to make", "karaoke", "backing track", "instrumental version",
    "cover by", "(cover)", "[cover]", "guitar cover", "piano cover",
    "drum cover", "bass cover", "reaction",
)

# Spotify titles carry the version after " - " ("Wompa - Mixed",
# "Songs Of Praise - Radio Edit") and the guests in a parenthetical
# ("Peace of Mind (feat. Delilah)"). Neither survives onto YouTube reliably,
# so containment is tested against the CORE title.
_TITLE_SEPARATORS = (" - ", " – ", " — ")


def is_reproduction(youtube_title: Optional[str],
                    channel: Optional[str] = None) -> bool:
    """True when the candidate is a re-creation (remake / tutorial / karaoke /
    cover) rather than the released recording. Measured case: KETTAMA's
    'Fly Away XTC (Ableton Remake)' matched title, artist AND duration to 1 s."""
    hay = f" {str(youtube_title or '').lower()} | {str(channel or '').lower()} "
    return any(marker in hay for marker in _REPRODUCTION_MARKERS)


def _core_title_text(track_name: Optional[str]) -> str:
    """The song title with Spotify's version suffix and any parenthetical
    dropped, but words kept: 'Bliss - XX Anniversary RemiXX' → 'Bliss',
    '5 Star (feat. Fayyaz Virji)' → '5 Star '."""
    name = str(track_name or "")
    for sep in _TITLE_SEPARATORS:
        if sep in name:
            name = name.split(sep)[0]
            break
    return re.sub(r"[(\[][^)\]]*[)\]]", " ", name)  # (feat. X) / [Radio Edit]


def core_title(track_name: Optional[str]) -> str:
    """The core title squashed for comparison. 'Wompa - Mixed' → 'wompa'."""
    return _squash(_core_title_text(track_name))


def title_contained(track_name: Optional[str],
                    youtube_title: Optional[str]) -> bool:
    """True when the track's core title actually appears in the candidate's
    title. Directional on purpose: the candidate may carry EXTRA words (artist,
    "Official Audio"), but it must contain the song's name — a shared stray
    token is not evidence ('Up & Down' vs 'Spice Up My Life')."""
    core = core_title(track_name)
    if len(core) < 2:                       # a 1-char title proves nothing
        return False
    return core in _squash(youtube_title)


def title_recall(track_name: Optional[str],
                 youtube_title: Optional[str]) -> float:
    """Fraction of the track's meaningful title tokens present in the candidate.

    A SOFTER measure than `title_contained` for the provenance REVIEW (not the
    auto-accept gate): it tolerates word order ('Black Sheep - Metric'),
    spelling ('Rumors' vs 'Rumours' — 3 of 4 tokens still land), and measures
    only the CORE title so a remix/feat suffix on our side can't dilute it
    ('Bliss - XX Anniversary RemiXX' → just 'bliss', which 'Muse - Bliss'
    fully contains). Short tokens (<4 chars) must match a whole token; longer
    ones may match inside the squashed title ('airmaxes' ⊇ 'air maxes').
    1.0 = every word is there; 0.0 = the song's name is not recognisably in the
    candidate — the real-miss signal."""
    toks = _tokens(_core_title_text(track_name))
    if not toks:
        return 0.0
    yt_toks = _tokens(youtube_title)
    yt_squash = _squash(youtube_title)
    present = sum(1 for t in toks
                  if t in yt_toks or (len(t) >= 4 and t in yt_squash))
    return present / len(toks)


def version_mismatch(track_name: Optional[str],
                     youtube_title: Optional[str]) -> Optional[str]:
    """The TAKE, not the song: does the source's version qualifier match ours?

    `title_recall` deliberately measures only the CORE title, so a remix sourced
    from its original scores 1.0 — the song IS recognisable, it is simply the
    wrong recording. `confident_match` misses the same class (these score
    0.80–0.85 on the live corpus: right song, right artist, plausible length).
    Nothing else in this module can see it, so this is the instrument for it,
    built on O4's `parse_title` — the one definition of "what version is this".

    Returns a human-readable reason when the takes disagree, else None:
        "on & on - Sammy Virji Remix"      ← "piri & tommy - on & on"   (0.80)
        "Low Again - Niall T Remix"        ← "Low Again"                (0.85)
        "Phonky Tribu - DJ HEARTSTRING Remix" ← "Funk Tribu - Phonky Tribu"

    A REVIEW/quarantine instrument, NOT an auto-accept gate (journal #52: a
    write gate and a health verdict want different bars). `parse_title` was
    tuned on Spotify titles; YouTube titles are noisier, so an untagged upload
    of a genuine remix reads as a mismatch here. That asymmetry is deliberate —
    a wrongly-flagged track is blanked pending a source, never deleted from the
    catalogue."""
    from ..store.dedup import parse_title  # stdlib-only, no cycle

    if not track_name or not youtube_title:
        return None
    our_base, want = parse_title(track_name)
    _, got = parse_title(youtube_title)
    if want == got:
        return None

    want_toks, got_toks = set(want.split()), set(got.split())
    # The source names the SAME take and merely says more about it
    # ("Let It Ride - Live on Display" ← "(Official Video - Live on Display)").
    # Only in this direction: if OUR tag says more, the source is a lesser take.
    if want_toks and want_toks <= got_toks:
        return None
    # The song is NAMED after a version word ("Speed Garage" by Bradderz), so
    # the source repeating the title is not a version claim at all.
    if got and got == our_base:
        return None

    if want and not got:
        return f"track is the {want!r} take but the source looks like the original"
    if got and not want:
        return f"track is the plain take but the source is the {got!r} version"
    return f"track is the {want!r} take but the source is the {got!r} version"


def leading_artist_segment(youtube_title: Optional[str]) -> Optional[str]:
    """The part of a candidate title before its 'Artist - Title' separator, or
    None when it has none. Our artist appearing AFTER the separator is usually
    a remix credit on somebody else's record ('Calvin Harris - I'm Not Alone
    (MPH Remix)' is not MPH's track 'Alone')."""
    title = str(youtube_title or "")
    for sep in _TITLE_SEPARATORS:
        if sep in title:
            return title.split(sep)[0]
    return None


def artist_affinity(artist: Optional[str], youtube_title: Optional[str],
                    channel: Optional[str] = None, *,
                    require_channel: bool = False) -> bool:
    """True when the candidate visibly belongs to THIS artist.

    Evidence, strongest first: the channel is the artist's own (or their
    auto-generated 'X - Topic'), or the title's leading-artist segment names
    them. `require_channel` keeps only the first — the bar the owner set for
    unattended repair of the existing corpus, where a wrong write is worse
    than no write."""
    a = _tokens(artist)
    if not a:
        return False
    if a & _tokens(channel):
        return True
    if require_channel:
        return False
    lead = leading_artist_segment(youtube_title)
    # No separator → no leading segment to isolate, so the whole title counts.
    return bool(a & _tokens(lead if lead is not None else youtube_title))


def duration_mismatch(candidate_s: Optional[float], expected_s: Optional[float],
                      tol_s: Optional[float] = None) -> bool:
    """TWO-SIDED length check for auto-accept. Unknown either side → mismatch:
    at this bar, absence of evidence is not evidence (contrast
    `implausible_duration`, a backstop that must not fire on the unknown).

    Default tolerance is the looser of 20 s and 15% — an official upload sits
    within a few seconds, while intros/outros and fades move legitimate ones
    by a little. Callers draining the repair queue pass a tighter value."""
    if not candidate_s or not expected_s or candidate_s <= 0 or expected_s <= 0:
        return True
    tol = tol_s if tol_s is not None else max(20.0, 0.15 * float(expected_s))
    return abs(float(candidate_s) - float(expected_s)) > tol


def confident_match(track_name: Optional[str], artist: Optional[str],
                    candidate: Optional[dict], expected_s: Optional[float], *,
                    require_channel: bool = False,
                    tol_s: Optional[float] = None) -> bool:
    """The auto-accept bar: may this candidate become the track's audio with
    no human looking? Every clause must hold — it is a conjunction because
    each one alone was measured admitting a wrong song."""
    if not candidate:
        return False
    title, channel = candidate.get("title"), candidate.get("channel")
    dur = candidate.get("youtube_duration_s")
    return (not is_reproduction(title, channel)
            and title_contained(track_name, title)
            and artist_affinity(artist, title, channel,
                                require_channel=require_channel)
            and not duration_mismatch(dur, expected_s, tol_s)
            and not implausible_duration(dur, expected_s))


def select_confident(candidates: list, track_name: Optional[str],
                     artist: Optional[str], expected_s: Optional[float], *,
                     require_channel: bool = False,
                     tol_s: Optional[float] = None) -> Optional[dict]:
    """FILTER, then rank — the inversion that matters.

    heuristic-v1 ranked first and the guards then judged the single winner, so
    a usable candidate sitting at position 2 of the same search was discarded
    unseen. Here every candidate faces the gate and the best SURVIVOR wins;
    when none survives the caller sends the track to manual repair.
    Ties break on the matcher's score, then url — deterministic."""
    ok = [c for c in (candidates or [])
          if confident_match(track_name, artist, c, expected_s,
                             require_channel=require_channel, tol_s=tol_s)]
    if not ok:
        return None
    return max(ok, key=lambda c: (c.get("score") or 0, str(c.get("url") or "")))


def rejection_reason(track_name: Optional[str], artist: Optional[str],
                     candidate: Optional[dict], expected_s: Optional[float], *,
                     require_channel: bool = False,
                     tol_s: Optional[float] = None) -> str:
    """Which clause refused this candidate — for the ledger and the QA report.
    An error message that names the real cause (QA_PLAN B6: "download failed"
    when conversion failed cost the owner two blind retries)."""
    if not candidate:
        return "no candidates"
    title, channel = candidate.get("title"), candidate.get("channel")
    dur = candidate.get("youtube_duration_s")
    if is_reproduction(title, channel):
        return "reproduction (remake/tutorial/karaoke), not the release"
    if not title_contained(track_name, title):
        return "title mismatch — the song's name is not in the candidate"
    if not artist_affinity(artist, title, channel, require_channel=require_channel):
        return ("channel is not the artist's" if require_channel
                else "artist mismatch — not the performer on this candidate")
    if duration_mismatch(dur, expected_s, tol_s):
        return (f"length mismatch — {dur or 0:.0f}s vs expected "
                f"{expected_s or 0:.0f}s")
    if implausible_duration(dur, expected_s):
        return f"wrong version — {dur or 0:.0f}s vs expected {expected_s or 0:.0f}s"
    return "rejected"


def describe(candidate: Optional[dict]) -> dict[str, Any]:
    """Compact, log-safe view of a candidate (no full entry dumps)."""
    c = candidate or {}
    return {"title": c.get("title"), "channel": c.get("channel"),
            "duration_s": c.get("youtube_duration_s"), "url": c.get("url")}
