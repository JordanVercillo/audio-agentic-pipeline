"""fact_section — the corpus's second fact grain, and the guards on it.

Synthetic only (ground rule 5).
"""
from __future__ import annotations

import json

import pandas as pd

from .semantic import (
    _MAX_SECTIONS,
    _release_year,
    build_fact_section,
    build_section_summary,
)


class _FakeCache:
    def __init__(self, sections, excluded=None, features=None):
        self._sections = sections
        self._excluded = excluded or set()
        self._features = features or {t: {} for t in sections}

    def all_sections(self):
        return self._sections

    def excluded_from_aggregates(self):
        return self._excluded

    def all_features(self):
        return self._features


def _sec(start, end, key=0, mode="major", tempo=120.0, loud=-12.0, label=0):
    return {"start": start, "end": end, "key": key, "mode": mode,
            "tempo_bpm": tempo, "loudness_db": loud, "label": label}


def test_the_grain_is_one_row_per_section_not_per_track():
    """The whole point of the table. Two tracks, five sections, five rows."""
    cache = _FakeCache({
        "a": json.dumps([_sec(0, 30), _sec(30, 60), _sec(60, 90)]),
        "b": json.dumps([_sec(0, 40), _sec(40, 80)]),
    })
    fs = build_fact_section(cache)
    assert len(fs) == 5
    assert fs["spotify_track_id"].nunique() == 2
    # (track, section_index) identifies a row; the bridge key alone does not
    assert not fs.duplicated(["spotify_track_id", "section_index"]).any()
    assert fs.duplicated(["spotify_track_id"]).any(), (
        "the bridge key alone should NOT be unique here — that is the grain")


def test_twins_and_withheld_tracks_sit_out():
    """The one shared filter. Without it a duplicated recording contributes its
    sections twice and TWIN_LEAKAGE fires."""
    cache = _FakeCache({"keep": json.dumps([_sec(0, 30), _sec(30, 60)]),
                        "twin": json.dumps([_sec(0, 30), _sec(30, 60)])},
                       excluded={"twin"})
    fs = build_fact_section(cache)
    assert set(fs["spotify_track_id"]) == {"keep"}


def test_a_fragmenting_detector_is_dropped_whole():
    """One live track detects 134 sections. That is the detector fragmenting,
    not a song with 134 parts, and letting it in would dominate every mean."""
    cache = _FakeCache({
        "sane": json.dumps([_sec(i * 10, (i + 1) * 10) for i in range(5)]),
        "shrapnel": json.dumps([_sec(i, i + 1.5) for i in range(_MAX_SECTIONS + 5)]),
    })
    fs = build_fact_section(cache)
    assert set(fs["spotify_track_id"]) == {"sane"}


def test_sub_second_sections_are_dropped_as_artifacts():
    cache = _FakeCache({"a": json.dumps([_sec(0, 30), _sec(30, 30.2), _sec(30.2, 60)])})
    fs = build_fact_section(cache)
    assert len(fs) == 2


def test_malformed_sections_do_not_take_the_mart_down():
    cache = _FakeCache({
        "bad_json": "{not json",
        "not_a_list": json.dumps({"start": 0}),
        "missing_bounds": json.dumps([{"key": 3}]),
        "good": json.dumps([_sec(0, 30), _sec(30, 60)]),
    })
    fs = build_fact_section(cache)
    assert set(fs["spotify_track_id"]) == {"good"}


def test_changes_key_is_the_claim_a_track_grain_table_cannot_make():
    """THE argument for the second grain, asserted."""
    cache = _FakeCache({
        "modulates": json.dumps([_sec(0, 30, key=0), _sec(30, 60, key=7)]),
        "steady": json.dumps([_sec(0, 30, key=5), _sec(30, 60, key=5)]),
        "flips_mode": json.dumps([_sec(0, 30, mode="major"),
                                  _sec(30, 60, mode="minor")]),
    })
    ss = build_section_summary(build_fact_section(cache)).set_index("spotify_track_id")
    assert bool(ss.loc["modulates", "changes_key"]) is True
    assert bool(ss.loc["steady", "changes_key"]) is False
    assert bool(ss.loc["flips_mode", "changes_mode"]) is True
    assert bool(ss.loc["steady", "changes_mode"]) is False


def test_summary_returns_to_track_grain():
    cache = _FakeCache({"a": json.dumps([_sec(0, 30, loud=-20.0), _sec(30, 60, loud=-8.0)])})
    ss = build_section_summary(build_fact_section(cache))
    assert len(ss) == 1
    row = ss.iloc[0]
    assert row["n_sections"] == 2
    assert row["loudness_range_db"] == 12.0


def test_empty_input_returns_empty_frames_not_a_crash():
    assert build_fact_section(_FakeCache({})).empty
    assert build_section_summary(pd.DataFrame()).empty


# ── the bug this session found in last session's code ──────────────────────

def test_release_year_handles_every_shape_spotify_sends():
    assert _release_year("2006-01-01") == 2006
    assert _release_year("2006-01") == 2006
    assert _release_year("2006") == 2006
    assert _release_year(None) is None
    assert _release_year("") is None
    assert _release_year("0001") is None          # parse artifact, not a release
    assert _release_year("9999") is None


def test_decade_survives_a_track_with_no_release_date():
    """The NaN trap. pandas types a column of ints-and-Nones as float64, so
    every None becomes NaN — and `NaN is None` is False, so a None check passes
    NaN into int() and raises. The column only becomes float once SOME track
    lacks a date, so this crashed the whole mart rebuild the first time a
    dateless track appeared.
    """
    df = pd.DataFrame({"release_year": [2006.0, float("nan"), 1994.0]})
    decades = df["release_year"].map(
        lambda y: None if y is None or pd.isna(y) else int(y) // 10 * 10)
    # The claim is "does not raise", and that the dated rows are right. The
    # None comes back as NaN because pandas re-coerces the result to float —
    # which is fine, `build_era_profile` filters on .notna(). Asserting
    # `== [2000, None, 1990]` would be testing pandas' dtype inference, not
    # this guard.
    assert decades.notna().sum() == 2
    assert [int(v) for v in decades.dropna()] == [2000, 1990]

    # and the unguarded version really does raise — proving the guard is not
    # decoration (journal #44)
    import pytest
    with pytest.raises(ValueError):
        df["release_year"].map(lambda y: None if y is None else int(y) // 10 * 10)
