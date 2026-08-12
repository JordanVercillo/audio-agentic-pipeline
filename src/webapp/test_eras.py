"""The era view — the demo's headline artifact, so its claims get tested.

Synthetic only (ground rule 5).
"""
from __future__ import annotations

import pandas as pd
import pytest

from .eras import MIN_TRACKS, era_chart_svg, era_rows, era_summary


def _mart(rows):
    return pd.DataFrame(rows)


def _row(decade, n=50, loud=-14.0, dur=220.0, tempo=120.0, artists=20):
    return {"decade": decade, "n_tracks": n, "mean_loudness_db": loud,
            "median_loudness_db": loud, "mean_tempo": tempo,
            "mean_duration_sec": dur, "n_artists": artists}


def test_thin_decades_are_dropped_not_drawn():
    """A 3-track decade is a handful of songs, not a period. Drawing it would
    put a headline on noise — the exact failure the ML work spent a session
    learning to avoid."""
    rows = era_rows(_mart([_row(1960, n=3), _row(2020, n=400)]))
    assert [r["decade"] for r in rows] == [2020]


def test_summary_is_derived_from_the_ends_not_hard_coded():
    """A typed '+4.1 dB' would be wrong within a week as the corpus grows —
    the README failure, reproduced on the demo's headline claim."""
    rows = era_rows(_mart([_row(1970, loud=-17.0, dur=270.0),
                           _row(2020, loud=-12.9, dur=206.0)]))
    s = era_summary(rows)
    assert s["from_decade"] == 1970 and s["to_decade"] == 2020
    assert s["loudness_delta_db"] == pytest.approx(4.1, abs=0.01)
    assert s["louder"] is True
    assert s["shorter"] is True
    assert s["n_total"] == 100


def test_a_reversed_trend_is_reported_as_reversed():
    """The page says 'louder'/'shorter' from the data. If a future corpus
    reverses, the words must reverse with it rather than the template
    asserting a direction the numbers do not support."""
    rows = era_rows(_mart([_row(1970, loud=-10.0, dur=180.0),
                           _row(2020, loud=-16.0, dur=300.0)]))
    s = era_summary(rows)
    assert s["louder"] is False and s["shorter"] is False


def test_one_decade_yields_no_summary():
    """Two points make a line through anything; one makes not even that."""
    assert era_summary(era_rows(_mart([_row(2020)]))) is None
    assert era_rows(_mart([])) == []


def test_chart_renders_a_point_per_decade_and_labels_them():
    rows = era_rows(_mart([_row(1990), _row(2000), _row(2010)]))
    svg = era_chart_svg(rows, "mean_loudness_db", "Mean loudness", " dBFS")
    assert svg.count("<circle") == 3
    for d in ("1990s", "2000s", "2010s"):
        assert d in svg
    assert "role=\"img\"" in svg and "<title>" in svg   # accessible


def test_chart_is_empty_rather_than_misleading_with_one_point():
    assert era_chart_svg(era_rows(_mart([_row(2020)])),
                         "mean_loudness_db", "x", "") == ""


def test_min_tracks_threshold_is_the_one_the_mart_uses():
    """The page prints this number; if the two drifted the caption would
    describe a rule the data does not follow."""
    from ..store.semantic import _MIN_TRACKS_PER_DECADE
    assert MIN_TRACKS == _MIN_TRACKS_PER_DECADE
