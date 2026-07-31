"""
test_explore.py — the Audio-Feature Explorer (VISION_SPECS F3), synthetic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from . import config
from .app import create_app
from .explore import (
    catalog_groups,
    histogram_svg,
    percentile_of,
    scatter_xy_svg,
    window_strip,
)

# ── mart loaders: fresh files served without a restart ──────────────────────


def test_loaders_pick_up_rewritten_marts(tmp_path, monkeypatch):
    """The worker rebuilds marts after extractions — the RUNNING webapp must
    serve the new file on the next request (mtime-keyed, no restart)."""
    import os

    from . import explore
    monkeypatch.setattr(explore, "_MARTS", tmp_path)
    cat = tmp_path / "feature_catalog.parquet"

    pd.DataFrame([{"column": "tempo", "tier": "measured"}]).to_parquet(cat, index=False)
    os.utime(cat, ns=(1_000_000_000, 1_000_000_000))
    assert len(explore.load_catalog()) == 1

    pd.DataFrame([{"column": "tempo", "tier": "measured"},
                  {"column": "energy", "tier": "derived"}]).to_parquet(cat, index=False)
    os.utime(cat, ns=(2_000_000_000, 2_000_000_000))
    assert len(explore.load_catalog()) == 2  # new content, same process

    assert explore.load_stats() is None      # absent mart still degrades to None


# ── pure view logic ─────────────────────────────────────────────────────────


def test_percentile_of_exact():
    pop = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile_of(5, pop) == 50
    assert percentile_of(10, pop) == 100
    assert percentile_of(0.5, pop) == 0
    assert percentile_of(3.0, []) == 50  # graceful empty population


def _stats_row():
    return pd.Series({"bin_edges": [0.0, 0.5, 1.0], "bin_counts": [3, 7],
                      "n": 10, "p50": 0.6, "min": 0.0, "max": 1.0})


def test_histogram_svg_bars_dots_and_axis():
    svg = histogram_svg(_stats_row(), user_values=[0.25, 0.9])
    assert svg.startswith("<svg") and svg.count("<rect") == 2      # one bar per bin
    assert svg.count('fill="#1db954"') == 2                        # the visitor's dots
    assert "<title>you: 0.25</title>" in svg
    assert "<title>0–0.5: 3 songs</title>" in svg                  # hover layer
    assert ">0</text>" in svg and ">1</text>" in svg               # axis min/max


def test_scatter_xy_svg_rings_user_and_grays_unclustered():
    points = [{"id": f"p{i}", "x": float(i), "y": float(i % 4),
               "cluster_id": (i % 2) if i < 6 else None, "name": f"P{i}"}
              for i in range(8)]
    svg = scatter_xy_svg(points, {"p0"}, x_label="Tempo", y_label="Energy")
    assert 'stroke="#171a21"' in svg and "<title>P0</title>" in svg  # ringed + named
    assert 'fill="#9aa0ac"' in svg                                   # unclustered = gray
    assert "Tempo →" in svg and "Energy →" in svg                    # labeled axes
    assert scatter_xy_svg(points[:2], set(), x_label="a", y_label="b") is None


def test_window_strip_means_and_delta():
    strip = window_strip({"short_term": [130.0, 134.0], "long_term": [120.0, 122.0]},
                         unit="bpm")
    assert [w["label"] for w in strip["windows"]] == ["Last 4 weeks", "All time"]
    assert strip["windows"][0]["mean"] == 132.0
    assert "11 bpm higher" in strip["delta"]
    assert window_strip({}, unit="") is None
    assert window_strip({"short_term": [1.0]}, unit="")["delta"] is None  # one window


def test_catalog_groups_tier_order():
    cat = pd.DataFrame([
        {"column": "valence_proxy", "tier": "experimental"},
        {"column": "tempo", "tier": "measured"},
        {"column": "energy", "tier": "derived"},
    ])
    groups = catalog_groups(cat)
    assert [g["tier"] for g in groups] == ["measured", "derived", "experimental"]


# ── the route ───────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _seed_session(taste=None):
    from .app import _signer, _store
    sid = _store.new()
    sess = _store.get(sid)
    sess["token"] = {"access_token": "x"}
    if taste is not None:
        sess["taste"] = taste
    return _signer.sign(sid)


def test_explore_unauthenticated_redirects(client):
    r = client.get("/explore", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_explore_without_dashboard_redirects(client):
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste={}))
    r = client.get("/explore", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_explore_marts_not_built_state(client, monkeypatch):
    monkeypatch.setattr("src.webapp.app.load_catalog", lambda: None)
    monkeypatch.setattr("src.webapp.app.load_stats", lambda: None)
    client.cookies.set(config.SESSION_COOKIE, _seed_session(
        taste={"range_ids": {"short_term": ["t1"]}}))
    r = client.get("/explore")
    assert r.status_code == 200 and "build_feature_marts" in r.text


def _synthetic_marts():
    catalog = pd.DataFrame([
        {"column": "tempo", "tier": "measured", "unit": "bpm",
         "friendly": "Tempo", "description": "Estimated tempo."},
        {"column": "energy", "tier": "derived", "unit": "0–1",
         "friendly": "Energy", "description": "Perceived intensity."},
        {"column": "danceability", "tier": "derived", "unit": "0–1",
         "friendly": "Danceability", "description": "Dance-floor fit."},
    ])
    stats = pd.DataFrame([
        {"column": "tempo", "bin_edges": [60.0, 120.0, 180.0], "bin_counts": [2, 2],
         "n": 4, "p50": 120.0, "min": 60.0, "max": 180.0},
        {"column": "energy", "bin_edges": [0.0, 0.5, 1.0], "bin_counts": [2, 2],
         "n": 4, "p50": 0.5, "min": 0.0, "max": 1.0},
        {"column": "danceability", "bin_edges": [0.0, 0.5, 1.0], "bin_counts": [1, 3],
         "n": 4, "p50": 0.7, "min": 0.0, "max": 1.0},
    ]).set_index("column")
    return catalog, stats


def test_explore_happy_path(client, monkeypatch, tmp_path):
    from ..store.cache import FeatureCache
    catalog, stats = _synthetic_marts()
    monkeypatch.setattr("src.webapp.app.load_catalog", lambda: catalog)
    monkeypatch.setattr("src.webapp.app.load_stats", lambda: stats)

    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'x.db'}")
    vals = [("u1", 130.0, 0.9, 0.95), ("u2", 70.0, 0.2, 0.30),
            ("pop1", 100.0, 0.5, 0.50), ("pop2", 160.0, 0.7, 0.80)]
    for tid, tempo, energy, dance in vals:
        tc.upsert_perceptual(tid, {"tempo": tempo, "energy": energy,
                                   "danceability": dance}, version="perceptual-v1")
        tc.remember_meta([{"spotify_track_id": tid, "track_name": tid.upper(),
                           "artist_names": "A"}])
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)

    taste = {"range_ids": {"short_term": ["u1"], "long_term": ["u2"]}}
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste=taste))
    r = client.get("/explore?f=danceability")
    assert r.status_code == 200
    assert "Danceability" in r.text and "tier-badge derived" in r.text
    assert 'class="hist"' in r.text                      # population histogram
    assert "your median" in r.text.lower()               # percentile chip
    assert 'class="how-to-read"' in r.text and "How to read the percentile" in r.text  # N1
    assert "at or below" in r.text
    assert 'class="cluster-map"' in r.text               # the scatter rendered
    assert "Last 4 weeks" in r.text                      # window strip
    # unknown feature falls back gracefully
    r2 = client.get("/explore?f=nonsense")
    assert r2.status_code == 200 and "Danceability" in r2.text

# ── P4.7.5: scatter sampling ─────────────────────────────────────────────────
def test_scatter_samples_the_background_but_never_the_visitors_tracks():
    """153 KB at ~1.9k tracks, growing with the corpus forever. Past a few
    hundred marks the extra dots add ink, not information — but the visitor's
    own tracks ARE the point of the chart, so they are never sampled out."""
    from .explore import _SCATTER_MAX, scatter_plotted_count, scatter_xy_svg

    pts = [{"id": f"t{i}", "x": float(i), "y": float(i % 7), "cluster_id": i % 2,
            "name": f"S{i}"} for i in range(2000)]
    mine = {f"t{i}" for i in range(0, 2000, 100)}          # 20 of the visitor's
    svg = scatter_xy_svg(pts, mine, x_label="X", y_label="Y")
    assert svg is not None
    drawn = svg.count("<circle")
    assert drawn <= _SCATTER_MAX + 5, f"sampling did not bound the chart ({drawn})"

    # Every one of the visitor's tracks survives the sampling. The SVG carries
    # no ids, so this used to read `assert tid in svg or ... or True` — an
    # assertion that cannot fail, guarding the claim that matters most on this
    # chart (director review 2026-07-31). The visitor's marks ARE identifiable:
    # they are the ringed r="5.5" circles, and they carry their track name.
    rings = svg.count('r="5.5"')
    assert rings == len(mine), (
        f"{rings} of the visitor's {len(mine)} tracks drawn — sampling ate "
        "the only points the chart exists to show")
    for tid in mine:
        assert f"<title>S{tid[1:]}</title>" in svg, f"{tid} was sampled out"

    # An exact contract, asserted exactly. The ±5 escape hatch that used to
    # follow this made the equality unfalsifiable in the range it could drift.
    assert scatter_plotted_count(pts, mine) == drawn


def test_scatter_is_unsampled_below_the_ceiling():
    from .explore import scatter_plotted_count, scatter_xy_svg

    pts = [{"id": f"t{i}", "x": float(i), "y": float(i % 5), "cluster_id": 0,
            "name": f"S{i}"} for i in range(120)]
    assert scatter_plotted_count(pts, set()) == 120
    svg = scatter_xy_svg(pts, set(), x_label="X", y_label="Y")
    assert svg.count("<circle") >= 120


def test_scatter_sampling_is_deterministic():
    """A chart that shimmers between reloads reads as instability."""
    from .explore import scatter_xy_svg

    pts = [{"id": f"t{i}", "x": float(i), "y": float(i % 11), "cluster_id": i % 3,
            "name": f"S{i}"} for i in range(1500)]
    a = scatter_xy_svg(pts, {"t5"}, x_label="X", y_label="Y")
    b = scatter_xy_svg(pts, {"t5"}, x_label="X", y_label="Y")
    assert a == b
