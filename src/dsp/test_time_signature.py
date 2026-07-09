"""
test_time_signature.py — the estimated meter (F-v2b), synthetic.

The estimator reads beat-accent periodicity; crafted accent patterns pin the
math, and a real DSP pass on a synthetic signal proves the plumbing. Honest by
design: weak/ambiguous evidence returns 4 rather than inventing a meter.
"""

from __future__ import annotations

import numpy as np

from .audio_loader import generate_test_signal
from .feature_extractor import _estimate_time_signature, time_signature_from_signal


def test_estimate_meter_picks_the_accent_period():
    beats = np.arange(16)
    onset3 = np.zeros(16)
    onset3[::3] = 1.0                          # a downbeat every 3rd beat → 3
    assert _estimate_time_signature(onset3, beats) == 3
    onset4 = np.zeros(16)
    onset4[::4] = 1.0                          # every 4th beat → 4
    assert _estimate_time_signature(onset4, beats) == 4


def test_estimate_meter_defaults_to_four_when_weak():
    assert _estimate_time_signature(np.zeros(20), np.arange(20)) == 4   # no accents
    assert _estimate_time_signature(np.ones(20), np.arange(5)) == 4     # too few beats
    assert _estimate_time_signature(np.array([]), np.array([])) == 4    # empty


def test_time_signature_from_signal_returns_plausible_meter():
    ts = time_signature_from_signal(generate_test_signal(frequency_hz=220.0, duration_sec=8.0))
    assert isinstance(ts, int) and 2 <= ts <= 7


def test_extract_sets_time_signature():
    from .feature_extractor import extract_features
    tf = extract_features(generate_test_signal(frequency_hz=220.0, duration_sec=6.0))
    assert isinstance(tf.time_signature, int) and 2 <= tf.time_signature <= 7
    assert "time_signature" not in tf.to_summary_dict()   # promoted column, not a contract feature
    assert len(tf.to_summary_vector()) == 77               # frozen vector untouched


def test_extract_sets_beat_grid():
    from .feature_extractor import beat_grid_from_signal, extract_features
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=6.0)
    tf = extract_features(sig)
    bt = tf.beat_times_list()
    assert isinstance(bt, list) and all(0.0 <= t <= 6.1 for t in bt)  # seconds, in range
    assert bt == sorted(bt)                                # beats are ordered
    assert isinstance(beat_grid_from_signal(sig), list)    # cheap backfill path agrees in shape
    assert "beat_times" not in tf.to_summary_dict()        # display data, not a contract feature
