"""Tests for the acquisition acceptance gate (QA2).

The fixtures ARE the live failures. Every wrong match in here was actually
admitted into the corpus (or would have been, measured over the needs-source
queue on 2026-07-23), and every accepted one is a real recording the gate must
not refuse. Pure functions, no network — ground rule 5.
"""

from .match_gate import (
    artist_affinity,
    confident_match,
    core_title,
    duration_mismatch,
    is_reproduction,
    rejection_reason,
    select_confident,
    title_contained,
)


def _cand(title, channel=None, dur=None, score=0, url="https://y/1"):
    return {"title": title, "channel": channel, "youtube_duration_s": dur,
            "score": score, "url": url}


# ── the four measured false positives ────────────────────────────────────────

def test_rejects_the_four_wrong_songs_that_passed_the_old_guards():
    # Each of these cleared implausible_duration AND title_affinity on
    # 2026-07-23 — they are why this module exists.

    # single shared token "up" — a different Sammy Virji song, Δ3s
    assert not confident_match(
        "Up & Down", "Sammy Virji",
        _cand("Sammy Virji - Spice Up My Life feat. Paige Eliza (Official Audio)",
              "Sammy Virji", 242.0), 239.0)

    # single shared token "i" — a different Denon Reed song, Δ9s
    assert not confident_match(
        "I need to know", "Denon Reed",
        _cand("MLT X Denon Reed - I never had", "Denon Reed", 147.0), 138.0)

    # our artist is the REMIXER, not the performer — "alone" is a substring of
    # "I'm Not Alone", and MPH really does appear in the title
    assert not confident_match(
        "Alone", "MPH",
        _cand("Calvin Harris - I'm Not Alone (MPH Remix - Official Audio)",
              "Calvin Harris", 215.0), 206.0)

    # right title, right artist, Δ1s — and a production tutorial, not the track
    assert not confident_match(
        "Fly Away XTC", "KETTAMA",
        _cand("KETTAMA - Fly Away XTC (Ableton Remake)",
              "Ableton Live Templates", 278.0), 277.0)


def test_accepts_the_genuinely_correct_matches():
    # Verified by hand from the same sweep — refusing these would be the
    # opposite failure (a queue nobody can drain).
    assert confident_match("Lights On", "The Blue Stones",
                           _cand("The Blue Stones - Lights On (Official Audio)",
                                 "The Blue Stones", 186.0), 189.0)
    assert confident_match("Twizzy", "Panteros666",
                           _cand("Panteros666, MCYL - Twizzy", "Panteros666",
                                 180.0), 180.0)
    assert confident_match("305 LUV STORY", "Gonzy",
                           _cand("GONZY - 305 LUV STORY (Official Video)",
                                 "Gonzy", 234.0), 217.0)
    # Spotify's version suffix must not break containment…
    assert confident_match("Wompa - Mixed", "MPH",
                           _cand("Wompa (Mixed)", "MPH - Topic", 112.0), 112.0)
    # …nor a feat-parenthetical, and the channel alone may carry the artist
    assert confident_match("Peace of Mind (feat. Delilah)", "Hutcher, GEE LEE",
                           _cand("Peace of Mind (feat. Delilah)", "Hutcher",
                                 198.0), 197.0)


# ── the individual clauses ───────────────────────────────────────────────────

def test_core_title_strips_spotify_version_and_parentheticals():
    assert core_title("Wompa - Mixed") == "wompa"
    assert core_title("Songs Of Praise - Radio Edit") == "songsofpraise"
    assert core_title("Peace of Mind (feat. Delilah)") == "peaceofmind"
    assert core_title("EL MUNDO ES MÍO") == "elmundoesmio"     # accents folded
    assert core_title(None) == ""


def test_title_contained_needs_the_song_name_not_a_shared_word():
    assert title_contained("Lights On", "The Blue Stones - Lights On (Official)")
    assert title_contained("Q&A", "Drake - Q&A Lyrics (DLyrics01)")
    assert not title_contained("Up & Down", "Sammy Virji - Spice Up My Life")
    assert not title_contained("I need to know", "MLT X Denon Reed - I never had")
    assert not title_contained("", "anything")                  # proves nothing


def test_artist_affinity_uses_the_leading_segment_not_a_remix_credit():
    # after the separator = a credit on someone else's record
    assert not artist_affinity("MPH", "Calvin Harris - I'm Not Alone (MPH Remix)",
                               "Calvin Harris")
    # before it = the performer
    assert artist_affinity("Skream", "Partiboi69 & Skream - Pound Town", "Partiboi69")
    # no separator → nothing to isolate, so the whole title counts
    assert artist_affinity("Hutcher", "Peace of Mind (feat. Delilah)", "SomeChannel") is False
    assert artist_affinity("Hutcher", "Hutcher Peace of Mind", "SomeChannel")
    # the artist's own / auto-generated Topic channel is the strongest evidence
    assert artist_affinity("MPH", "Wompa (Mixed)", "MPH - Topic")
    assert not artist_affinity("", "anything", "anything")      # unknown ≠ pass


def test_require_channel_keeps_only_the_artists_own_channel():
    # the bar the owner set for unattended repair of the existing corpus
    assert artist_affinity("Gonzy", "GONZY - 305 LUV STORY", "Gonzy",
                           require_channel=True)
    assert not artist_affinity("Bad Bunny", "Bad Bunny - El Mundo Es Mio",
                               "GreatAudios", require_channel=True)
    # …but the same candidate is admissible at the live-ingestion bar
    assert artist_affinity("Bad Bunny", "Bad Bunny - El Mundo Es Mio", "GreatAudios")


def test_duration_is_two_sided_and_unknown_never_passes():
    assert not duration_mismatch(200.0, 197.0)          # an official upload
    assert duration_mismatch(83.0, 182.0)               # the 'Logic Pro Remake' stub
    assert duration_mismatch(7396.0, 207.0)             # a DJ set
    assert not duration_mismatch(217.0, 199.0)          # intro/outro drift, within 15%
    assert duration_mismatch(217.0, 199.0, tol_s=10.0)  # …not at a tighter bar
    assert duration_mismatch(None, 200.0)               # unknown is NOT a pass
    assert duration_mismatch(200.0, None)


def test_is_reproduction_catches_remakes_but_not_legitimate_remixes():
    assert is_reproduction("KETTAMA - Fly Away XTC (Ableton Remake)")
    assert is_reproduction("SOSA (UK) - The Connection (Ableton Remake)",
                           "Top Music Arts")
    assert is_reproduction("How To Make A Garage Beat - FL Studio Tutorial")
    assert is_reproduction("Song X (Karaoke Version)")
    # S2 sign-off: remixes/bootlegs/edits are real corpus members
    assert not is_reproduction("Airmaxes (KETTAMA MIX)")
    assert not is_reproduction("Boasty (Conducta Remix)")
    assert not is_reproduction("Sammy Virji - Damager (Becking Bootleg)")


# ── filter-then-rank ─────────────────────────────────────────────────────────

def test_select_confident_finds_the_survivor_below_the_top_score():
    # THE inversion: the highest-scoring candidate is inadmissible while a real
    # one sits underneath it. Rank-then-reject discarded the whole search.
    candidates = [
        _cand("Riordan B2B Silva Bumpa in a Skate Park | RAW CUTS", "RAW", 7397.0,
              score=25, url="https://y/mix"),
        _cand("Riordan - WGTF? (Official Audio)", "Riordan", 205.0,
              score=10, url="https://y/real"),
    ]
    chosen = select_confident(candidates, "WGTF?", "Riordan", 207.0)
    assert chosen is not None and chosen["url"] == "https://y/real"


def test_select_confident_returns_none_when_nothing_is_admissible():
    candidates = [_cand("Some 2 Hour Mix", "DJ", 7200.0, score=25),
                  _cand("A Totally Different Song", "Someone", 200.0, score=20)]
    assert select_confident(candidates, "WGTF?", "Riordan", 207.0) is None
    assert select_confident([], "WGTF?", "Riordan", 207.0) is None


def test_select_confident_is_deterministic_on_ties():
    a = _cand("Riordan - WGTF? (Official Audio)", "Riordan", 205.0, score=10,
              url="https://y/aaa")
    b = _cand("Riordan - WGTF? (Official Audio)", "Riordan", 205.0, score=10,
              url="https://y/zzz")
    assert select_confident([a, b], "WGTF?", "Riordan", 207.0)["url"] == "https://y/zzz"
    assert select_confident([b, a], "WGTF?", "Riordan", 207.0)["url"] == "https://y/zzz"


def test_rejection_reason_names_the_real_cause():
    # QA_PLAN B6: a message that says what actually happened
    assert "reproduction" in rejection_reason(
        "Fly Away XTC", "KETTAMA",
        _cand("KETTAMA - Fly Away XTC (Ableton Remake)", "Ableton", 278.0), 277.0)
    assert "title" in rejection_reason(
        "Up & Down", "Sammy Virji",
        _cand("Sammy Virji - Spice Up My Life", "Sammy Virji", 242.0), 239.0)
    assert "artist" in rejection_reason(
        "Alone", "MPH",
        _cand("Calvin Harris - I'm Not Alone (MPH Remix)", "Calvin Harris", 215.0),
        206.0)
    assert "length" in rejection_reason(
        "Lights On", "The Blue Stones",
        _cand("The Blue Stones - Lights On", "The Blue Stones", 40.0), 189.0)
    assert rejection_reason("x", "y", None, 100.0) == "no candidates"
