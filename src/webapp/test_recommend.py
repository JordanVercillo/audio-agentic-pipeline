"""
test_recommend.py — the recommendation engine (Epic G), pure + synthetic.

The retired /recommendations semantics on our own features: min/max prune,
targets rank by z-distance, seeds fill visible targets, popularity rides as a
constraint axis. Deterministic by contract.
"""

from __future__ import annotations

import pandas as pd
import pytest

from . import config
from .app import create_app
from .recommend import (
    Constraint,
    parse_constraints,
    popularity_stats,
    recommend,
    seed_targets,
)

_ALLOWED = {"energy", "tempo", "danceability", "popularity"}
_STATS = {"energy": (0.5, 0.2), "tempo": (120.0, 30.0),
          "danceability": (0.5, 0.2), "popularity": (50.0, 20.0)}

_ROWS = {
    "slow_quiet":  {"energy": 0.2, "tempo": 80.0, "danceability": 0.3, "popularity": 20},
    "mid":         {"energy": 0.5, "tempo": 120.0, "danceability": 0.5, "popularity": 50},
    "fast_loud":   {"energy": 0.9, "tempo": 170.0, "danceability": 0.8, "popularity": 80},
    "no_pop":      {"energy": 0.55, "tempo": 125.0, "danceability": 0.55},  # missing popularity
}


def test_parse_constraints_whitelists_and_ignores_junk():
    got = parse_constraints(
        {"min_energy": "0.4", "max_tempo": "140", "target_danceability": "0.8",
         "target_hacked_column": "1", "min_energy_bogus": "9",  # unknown cols
         "target_popularity": "not-a-number", "seed": "x", "max_energy": ""},
        _ALLOWED)
    assert set(got) == {Constraint("energy", "min", 0.4),
                        Constraint("tempo", "max", 140.0),
                        Constraint("danceability", "target", 0.8)}


def test_min_max_prune_and_targets_rank():
    cons = [Constraint("energy", "min", 0.4),          # drops slow_quiet
            Constraint("tempo", "target", 120.0)]
    got = recommend(_ROWS, cons, _STATS)
    ids = [r["id"] for r in got]
    assert "slow_quiet" not in ids
    assert ids[0] == "mid"                              # exact tempo match ranks first
    assert got[0]["score"] == 0.0 and got[0]["values"]["tempo"] == 120.0
    assert ids.index("no_pop") < ids.index("fast_loud")  # 125 closer than 170


def test_missing_constrained_value_excludes_track():
    got = recommend(_ROWS, [Constraint("popularity", "max", 60.0)], _STATS)
    ids = {r["id"] for r in got}
    assert "no_pop" not in ids                          # can't verify → don't guess
    assert ids == {"slow_quiet", "mid"}                 # 80 pruned by max


def test_z_normalized_distance_compares_axes_honestly():
    # one std away on tempo (30bpm) must tie one std away on energy (0.2)
    a = recommend({"t": {"tempo": 150.0}}, [Constraint("tempo", "target", 120.0)], _STATS)
    b = recommend({"e": {"energy": 0.7}}, [Constraint("energy", "target", 0.5)], _STATS)
    assert a[0]["score"] == b[0]["score"] == 1.0


def test_deterministic_ordering_breaks_ties_by_id():
    rows = {"b": {"energy": 0.5}, "a": {"energy": 0.5}}
    got = recommend(rows, [Constraint("energy", "target", 0.5)], _STATS)
    assert [r["id"] for r in got] == ["a", "b"]
    assert got == recommend(rows, [Constraint("energy", "target", 0.5)], _STATS)


def test_seed_targets_are_visible_constraints():
    cons = seed_targets({"energy": 0.9, "tempo": 170.0, "mode": None, "junk": 1.0},
                        _ALLOWED, popularity=80)
    assert Constraint("energy", "target", 0.9) in cons
    assert Constraint("popularity", "target", 80.0) in cons
    assert not any(c.column == "junk" for c in cons)    # whitelist holds
    # seeding ranks the seed's nearest neighbor first (seed itself excluded)
    got = recommend(_ROWS, cons, _STATS, exclude={"fast_loud"})
    assert got[0]["id"] == "mid"                        # nearer to fast_loud than slow_quiet
    assert got[-1]["id"] == "slow_quiet"


def test_zero_spread_axis_cannot_rank():
    stats = {"energy": (0.5, 0.0)}                      # degenerate corpus
    got = recommend({"x": {"energy": 0.9}}, [Constraint("energy", "target", 0.1)], stats)
    assert got[0]["score"] == 0.0                       # no false precision


def test_popularity_stats():
    mean, std = popularity_stats({"a": 40, "b": 60})
    assert mean == 50.0 and std == 10.0
    assert popularity_stats({"a": 40}) is None
    assert popularity_stats({}) is None


# ── the /recommend route ─────────────────────────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _catalog():
    return pd.DataFrame([
        {"column": "energy", "friendly": "Energy", "tier": "derived", "unit": "0–1"},
        {"column": "tempo", "friendly": "Tempo", "tier": "measured", "unit": "bpm"},
    ])


def _stats():
    return pd.DataFrame([
        {"column": "energy", "mean": 0.5, "std": 0.2},
        {"column": "tempo", "mean": 120.0, "std": 30.0},
    ]).set_index("column")


def _reco_cache(tmp_path):
    from ..store.cache import FeatureCache
    tc = FeatureCache(url=f"sqlite:///{tmp_path / 'r.db'}")
    tracks = {"calm": (0.2, 80.0, 25), "steady": (0.5, 120.0, 55), "wild": (0.9, 170.0, 85)}
    metas = []
    for tid, (energy, tempo, pop) in tracks.items():
        tc.upsert_perceptual(tid, {"energy": energy, "tempo": tempo}, version="v1")
        metas.append({"spotify_track_id": tid, "track_name": tid.title(),
                      "artist_names": "Band", "popularity": pop})
    tc.remember_meta(metas)
    return tc


def _wire(monkeypatch, tc):
    monkeypatch.setattr("src.webapp.app._feature_cache", lambda: tc)
    monkeypatch.setattr("src.webapp.app.load_catalog", _catalog)
    monkeypatch.setattr("src.webapp.app.load_stats", _stats)


def test_recommend_unauthenticated_redirects(client):
    r = client.get("/recommend", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_recommend_without_dashboard_redirects(client):
    from .test_webapp import _seed_session
    client.cookies.set(config.SESSION_COOKIE, _seed_session(taste={"range_ids": {}}))
    r = client.get("/recommend", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_recommend_marts_not_built(client, monkeypatch):
    from .test_webapp import _seed_session
    monkeypatch.setattr("src.webapp.app.load_catalog", lambda: None)
    monkeypatch.setattr("src.webapp.app.load_stats", lambda: None)
    client.cookies.set(config.SESSION_COOKIE,
                       _seed_session(taste={"range_ids": {"short_term": ["x"]}}))
    r = client.get("/recommend")
    assert r.status_code == 200 and "marts not built" in r.text


def test_recommend_tunables_filter_and_rank(client, monkeypatch, tmp_path):
    from .test_webapp import _seed_session
    _wire(monkeypatch, _reco_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE,
                       _seed_session(taste={"range_ids": {"short_term": ["x"]}}))
    r = client.get("/recommend?min_energy=0.4&target_tempo=125")
    assert r.status_code == 200
    body = r.text[r.text.index("reco-results"):]          # results, not the seed dropdown
    assert "Calm" not in body                             # pruned by min_energy
    assert body.index("Steady") < body.index("Wild")      # 120 closer to 125 than 170
    assert "tempo 120.0" in body                          # value chips
    # the form re-renders the active constraints
    assert 'name="min_energy"' in r.text and 'value="0.4"' in r.text


def test_recommend_seed_prefills_and_excludes_itself(client, monkeypatch, tmp_path):
    from .test_webapp import _seed_session
    _wire(monkeypatch, _reco_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE,
                       _seed_session(taste={"range_ids": {"short_term": ["x"]}}))
    r = client.get("/recommend?seed=wild")
    assert r.status_code == 200
    assert "More like" in r.text and "Wild" in r.text     # heading names the seed
    assert 'value="0.9"' in r.text                        # seeded target visible in the form
    body = r.text[r.text.index("reco-results"):]
    assert "Wild" not in body                             # the seed never recommends itself
    assert body.index("Steady") < body.index("Calm")      # nearest neighbor first
    # popularity seeded as a target too (fetched-context axis)
    assert 'name="target_popularity"' in r.text and 'value="85.0"' in r.text


def test_recommend_impossible_constraints_message(client, monkeypatch, tmp_path):
    from .test_webapp import _seed_session
    _wire(monkeypatch, _reco_cache(tmp_path))
    client.cookies.set(config.SESSION_COOKIE,
                       _seed_session(taste={"range_ids": {"short_term": ["x"]}}))
    r = client.get("/recommend?min_energy=0.95")
    assert "No cached track satisfies" in r.text
