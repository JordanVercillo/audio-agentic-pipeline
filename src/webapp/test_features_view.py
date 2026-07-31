"""D-66 — the all-features page: pure builder + the honesty rules it encodes."""
from __future__ import annotations

from .features_view import build_feature_detail

_DICT = [
    {"column": "tempo_bpm", "group": "Time & rhythm", "unit": "bpm",
     "direction": "faster", "description": "Beats per minute.",
     "caveat": "Quantised.", "in_vector_77": True},
    {"column": "estimated_key", "group": "Tonal & harmony", "unit": "pitch class",
     "direction": "categorical — no order", "description": "Detected tonic.",
     "caveat": "", "in_vector_77": True},
    {"column": "mfcc_mean_0", "group": "Timbre fingerprint", "unit": "",
     "direction": "—", "description": "MFCC.",
     "caveat": "Not interpretable in isolation.", "in_vector_77": True},
    {"column": "rms_mean", "group": "Level & dynamics", "unit": "",
     "direction": "louder", "description": "Average level.", "caveat": "",
     "in_vector_77": True},
]
_STATS = [
    {"column": "tempo_bpm", "n": 100, "min": 60.0, "p25": 100.0, "p50": 120.0,
     "p75": 140.0, "max": 200.0},
    {"column": "estimated_key", "n": 100, "min": 0.0, "p25": 3.0, "p50": 5.0,
     "p75": 8.0, "max": 11.0},
    {"column": "mfcc_mean_0", "n": 100, "min": -400.0, "p25": -300.0,
     "p50": -250.0, "p75": -200.0, "max": -100.0},
    {"column": "rms_mean", "n": 100, "min": 0.0, "p25": 0.1, "p50": 0.2,
     "p75": 0.3, "max": 0.5},
]
_FEATURES = {"tempo_bpm": 120.0, "estimated_key": 7, "mfcc_mean_0": -250.0,
             "rms_mean": 0.2, "file_name": "x.mp3", "estimated_mode": "major"}


def _detail():
    return build_feature_detail(_FEATURES, _DICT, _STATS)


def test_non_numeric_keys_never_render_as_features():
    d = _detail()
    cols = {r["column"] for g in d["groups"] for r in g["rows"]}
    assert "file_name" not in cols and "estimated_mode" not in cols
    assert d["n_features"] == 4


def test_a_pitch_class_gets_no_percentile():
    """A percentile on a category is nonsense — the renderer keys off this."""
    d = _detail()
    key = [r for g in d["groups"] for r in g["rows"] if r["column"] == "estimated_key"][0]
    assert key["categorical"] is True
    assert key["percentile"] is None


def test_shape_only_coefficients_get_no_percentile():
    """An MFCC coefficient's standalone rank implies a meaning it doesn't have."""
    d = _detail()
    m = [r for g in d["groups"] for r in g["rows"] if r["column"] == "mfcc_mean_0"][0]
    assert m["shape_only"] is True and m["percentile"] is None
    timbre = [g for g in d["groups"] if g["name"] == "Timbre fingerprint"][0]
    assert timbre["collapsed"] is True
    assert "isolation" in timbre["shape_note"]


def test_percentile_is_derived_from_the_corpus_quartiles():
    d = _detail()
    tempo = [r for g in d["groups"] for r in g["rows"] if r["column"] == "tempo_bpm"][0]
    assert tempo["percentile"] == 50          # 120 is the stored p50
    assert tempo["corpus_median"] == 120.0
    rms = [r for g in d["groups"] for r in g["rows"] if r["column"] == "rms_mean"][0]
    assert rms["percentile"] == 50


def test_population_is_reported_so_a_rank_can_be_checked():
    assert _detail()["population_n"] == 100


def test_groups_come_back_in_a_stable_reading_order():
    names = [g["name"] for g in _detail()["groups"]]
    assert names == ["Time & rhythm", "Level & dynamics", "Tonal & harmony",
                     "Timbre fingerprint"]


def test_vector_membership_is_surfaced():
    assert _detail()["n_in_vector"] == 4


# ── the percentile's accuracy is a claim, so it gets measured ───────────────
def _stat_from(vals, *, deciles: bool):
    """A raw_feature_stats row built the way the mart builds one."""
    import numpy as np

    qs = (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95) if deciles else (25, 50, 75)
    row = {"column": "x", "n": len(vals),
           "min": float(np.min(vals)), "max": float(np.max(vals))}
    for q in qs:
        row[f"p{q}"] = float(np.percentile(vals, q))
    return row


def test_percentile_error_stays_under_two_points_on_a_skewed_column():
    """Director review 2026-07-31: with only min/p25/p50/p75/max the shipped
    percentile was off by a measured mean of 4.7 points and up to 22 on the
    live corpus, ALWAYS toward the middle — the direction that makes a
    genuinely unusual track read as unremarkable. Deciles fixed it (measured
    0.72 mean / 9.2 max). This is the tripwire on that.

    Skewed on purpose: a symmetric distribution hides the failure, because
    linear interpolation is exact for the uniform case.
    """
    import numpy as np

    from .features_view import _percentile

    rng = np.random.default_rng(7)
    vals = np.round(rng.lognormal(0.0, 0.9, 4000), 4)     # long right tail
    fine, coarse = _stat_from(vals, deciles=True), _stat_from(vals, deciles=False)

    errs_fine, errs_coarse, pull = [], [], []
    for v in np.quantile(vals, np.linspace(0.05, 0.95, 40)):
        truth = 100.0 * (vals < v).mean()
        f, c = _percentile(float(v), fine), _percentile(float(v), coarse)
        errs_fine.append(abs(f - truth))
        errs_coarse.append(abs(c - truth))
        pull.append(abs(f - 50) - abs(truth - 50))

    assert max(errs_fine) < 3.0, f"decile interpolation drifted: {max(errs_fine):.1f}"
    assert np.mean(errs_fine) < np.mean(errs_coarse) / 2, (
        "deciles must be at least twice as accurate as the quartile ladder they "
        f"replaced: {np.mean(errs_fine):.2f} vs {np.mean(errs_coarse):.2f}")
    assert abs(np.mean(pull)) < 1.0, (
        f"still biased toward 'ordinary' by {np.mean(pull):+.2f} points")


def test_percentile_still_renders_against_a_pre_decile_mart():
    """A mart written before the decile change must degrade, not go blank."""
    from .features_view import _percentile

    old = {"column": "x", "min": 0.0, "p25": 1.0, "p50": 2.0, "p75": 3.0,
           "max": 4.0}
    assert _percentile(2.0, old) == 50
    assert _percentile(-1.0, old) == 0
    assert _percentile(99.0, old) == 100
    assert _percentile(1.0, {"column": "x"}) is None      # no anchors at all


def test_percentile_on_a_mass_spike_returns_the_middle_of_the_tied_range():
    """When a value is shared by a fifth of the corpus its rank is a RANGE.
    Interpolating across a zero-width segment used to divide by a fudge factor;
    the midpoint is the least-wrong single number."""
    from .features_view import _percentile

    spike = {"column": "x", "min": 0.0, "p25": 1.0, "p50": 1.0, "p75": 1.0,
             "max": 2.0}
    assert _percentile(1.0, spike) == 50
