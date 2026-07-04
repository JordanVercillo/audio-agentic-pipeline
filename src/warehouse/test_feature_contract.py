"""
test_feature_contract.py — the 82-dim warehouse feature contract (SPEC P6/D-4)
==============================================================================
Locks the DSP output to its documentation IN THE CODEBASE: every numeric
feature that TrackFeatures.to_summary_dict() produces must be documented in
modeled.COLUMN_DESCRIPTIONS, and vice-versa — exact set equality, no tolerance.

This is the unit-level twin of the warehouse-audit's exact-list check: the
audit verifies the DATA matches the contract; this verifies the CODE does, so
CI catches drift with synthetic data alone (no warehouse required).
"""

from src.dsp import extract_features, generate_test_signal
from src.warehouse.modeled import COLUMN_DESCRIPTIONS

# Documented columns that are metadata, not DSP features (identifiers, track
# metadata, tonal-class labels). Mirror of the audit's NON_FEATURE_DESCRIBED.
_NON_FEATURE = {
    "spotify_track_id", "time_range", "rank", "track_name", "artist_names",
    "primary_artist_name", "album_name", "duration_ms", "explicit",
    "estimated_key", "estimated_mode",
}
# Non-feature keys to_summary_dict emits (paths + tonal labels).
_DICT_EXCLUDE = {"file_name", "file_path", "estimated_key", "estimated_mode"}


def _documented_features() -> set[str]:
    return set(COLUMN_DESCRIPTIONS) - _NON_FEATURE


def _dsp_feature_columns() -> set[str]:
    signal = generate_test_signal(frequency_hz=440.0, duration_sec=2.0)
    summary = extract_features(signal).to_summary_dict()
    return {
        k for k, v in summary.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        and k not in _DICT_EXCLUDE
    }


def test_every_dsp_feature_is_documented():
    undocumented = _dsp_feature_columns() - _documented_features()
    assert not undocumented, f"DSP features missing a column_descriptions entry: {sorted(undocumented)}"


def test_no_documented_feature_is_missing_from_dsp():
    absent = _documented_features() - _dsp_feature_columns()
    assert not absent, f"Documented features not produced by the DSP: {sorted(absent)}"


def test_contract_is_the_expected_size():
    # 82 numeric DSP feature columns (the warehouse contract) — a canary so a
    # silent add/drop on BOTH sides still trips a review.
    assert len(_documented_features()) == 82
    assert len(_dsp_feature_columns()) == 82


if __name__ == "__main__":
    import sys

    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
