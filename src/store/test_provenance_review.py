"""Tests for the Q4 provenance-health review (pure). Synthetic rows shaped like
real `track_provenance` events; the classification cases mirror the live
match-quality tail. No I/O — ground rule 5."""

from . import provenance_review as pr


def _prov(tid, title, channel, dur, conf=0.85, delta=2.0, matcher="heuristic-v1"):
    return {"spotify_track_id": tid, "youtube_title": title, "channel": channel,
            "youtube_duration_s": dur, "match_confidence": conf,
            "duration_delta_s": delta, "matcher_version": matcher,
            "youtube_url": f"https://y/{tid}"}


def _meta(name, artist, dur_ms):
    return {"name": name, "artist": artist, "duration_ms": dur_ms}


# ── characterize ─────────────────────────────────────────────────────────────
def test_verified_official_match():
    c = pr.characterize(
        _prov("a", "The Blue Stones - Lights On (Official Audio)", "The Blue Stones", 186.0),
        _meta("Lights On", "The Blue Stones", 189_000))
    assert c["tier"] == pr.TIER_VERIFIED


def test_title_present_remix_off_duration():
    # right artist, title present, a remix that runs long — fails the strict
    # gate on duration but the song is clearly there
    c = pr.characterize(
        _prov("b", "Sammy Virji - Damager (Becking Bootleg)", "Sammy Virji", 300.0,
              delta=75.0),
        _meta("Damager", "Sammy Virji", 225_000))
    assert c["tier"] == pr.TIER_TITLE_PRESENT


def test_review_wrong_song_title_absent():
    # the classic failure: a single shared token, the SONG NAME isn't there
    c = pr.characterize(
        _prov("c", "Sammy Virji - Spice Up My Life", "Sammy Virji", 242.0),
        _meta("Up & Down", "Sammy Virji", 239_000))
    assert c["tier"] == pr.TIER_REVIEW


def test_does_not_cry_wolf_on_obviously_right_songs():
    # THE false positives the first live sample exposed: the strict WRITE gate
    # rejects these on word order / spelling / artist-in-channel, but the song
    # is plainly the right one — they must NOT land in the review worklist.
    order = pr.characterize(                     # "Title - Artist" ordering
        _prov("o", "Black Sheep - Metric", "someuploader", 200.0),
        _meta("Black Sheep", "Metric", 200_000))
    spelling = pr.characterize(                   # Rumors vs Rumours
        _prov("s", "Rise Against - Rumours of my Demise Have Been Greatly Exaggerated",
              "Rise Against", 200.0),
        _meta("Rumors Of My Demise Have Been Greatly Exaggerated", "Rise Against", 200_000))
    handle = pr.characterize(                     # artist as a no-space @handle
        _prov("h", "@RedHotChiliPeppers - Dani California (Lyrics)", "lyricschan", 200.0),
        _meta("Dani California", "Red Hot Chili Peppers", 200_000))
    for c in (order, spelling, handle):
        assert c["tier"] != pr.TIER_REVIEW, c


def test_owner_supplied_is_trusted_without_machine_judgement():
    c = pr.characterize(
        _prov("e", "Owner-supplied audio file", None, 174.0, conf=None,
              matcher="manual-upload"),
        _meta("Roots", "WILDS", 174_000))
    assert c["tier"] == pr.TIER_OWNER


def test_missing_meta_lands_in_review():
    c = pr.characterize(_prov("f", "Something", "Chan", 200.0), None)
    assert c["tier"] == pr.TIER_REVIEW


# ── sampling ─────────────────────────────────────────────────────────────────
def _corpus():
    rows, metas = [], {}
    # 10 clean official matches (right artist, title contained, on duration)
    for i in range(10):
        rows.append(_prov(f"v{i}", "Muse - Hysteria (Official Audio)", "Muse", 200.0))
        metas[f"v{i}"] = _meta("Hysteria", "Muse", 200_000)
    # 30 real misses (a completely unrelated song under the wanted id)
    for i in range(30):
        rows.append(_prov(f"r{i}", "Someone Else - Different Tune", "Someone Else", 200.0))
        metas[f"r{i}"] = _meta("Wanted Track", "Wanted Artist", 200_000)
    return pr.characterize_all(rows, metas), metas


def test_sample_over_weights_the_review_tier_and_is_deterministic():
    ch, _ = _corpus()
    s1 = pr.stratified_sample(ch, size=20)
    s2 = pr.stratified_sample(ch, size=20)
    assert [r["id"] for r in s1] == [r["id"] for r in s2]      # deterministic
    n_review = sum(1 for r in s1 if r["tier"] == pr.TIER_REVIEW)
    assert n_review >= 12                                       # the miss candidates dominate


def test_thin_tier_never_blocks_the_sampler():
    ch = pr.characterize_all([_prov("v0", "Muse - Hysteria (Official Audio)", "Muse", 200.0)],
                             {"v0": _meta("Hysteria", "Muse", 200_000)})
    assert len(pr.stratified_sample(ch, size=20)) == 1


# ── worksheet escaping ───────────────────────────────────────────────────────
def test_worksheet_escapes_untrusted_youtube_title():
    ch = pr.characterize_all(
        [_prov("x", "<script>alert(1)</script>", "<b>chan</b>", 200.0)],
        {"x": _meta("Song", "Artist", 200_000)})
    card = pr.render_worksheet(ch, {"x": _meta("Song", "Artist", 200_000)})[0]
    assert "<script>" not in card["youtube_title"] and "&lt;script&gt;" in card["youtube_title"]
    assert "<b>" not in card["channel"]


# ── aggregation ──────────────────────────────────────────────────────────────
def test_aggregate_splits_the_tail_and_leaks_no_titles():
    ch, _ = _corpus()
    rep = pr.aggregate(ch, n_canonical=40)
    assert rep["n_current"] == 40 and rep["coverage_pct"] == 100.0
    assert rep["tiers"][pr.TIER_VERIFIED] == 10
    assert rep["tail"]["review"] == 30 and rep["tail"]["title_present"] == 0
    assert rep["pct_pass_current_gate"] == 25.0                 # 10 of 40 machine
    # aggregates-only: no external title string anywhere in the report
    blob = repr(rep)
    assert "Totally Other Song" not in blob and "Official Audio" not in blob


def test_format_report_states_the_tail_split():
    ch, _ = _corpus()
    text = pr.format_report(pr.aggregate(ch, n_canonical=40))
    assert "title-present" in text and "want-a-look" in text
    assert "coverage" in text and "pass gate" in text
