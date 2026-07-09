"""
test_loudness_curve.py — the within-track loudness curve (F-v2a), synthetic.

Pure downsampler math + a real-DSP pass on a synthetic signal (ground rule:
no downloaded audio). The curve is display data — it must never leak into the
frozen 77-dim vector or the 82-col summary dict.
"""

from __future__ import annotations

import math

import numpy as np

from .audio_loader import generate_test_signal
from .feature_extractor import (
    LOUDNESS_CURVE_POINTS,
    _downsample_loudness_db,
    extract_features,
)


def test_downsample_caps_length_and_is_dbfs():
    # A long constant RMS envelope → n_points values, all ~0 dBFS (20·log10 1 = 0).
    db = _downsample_loudness_db(np.ones(1000, dtype=float))
    assert len(db) == LOUDNESS_CURVE_POINTS
    assert db.dtype == np.float32
    assert np.allclose(db, 0.0, atol=1e-4)


def test_downsample_full_resolution_when_short():
    db = _downsample_loudness_db(np.array([1.0, 0.1, 0.01]))
    assert len(db) == 3                          # fewer frames than points → 1:1
    # 20·log10 of 1, 0.1, 0.01 = 0, -20, -40 dBFS
    assert np.allclose(db, [0.0, -20.0, -40.0], atol=1e-3)


def test_downsample_silence_floored_not_infinite():
    db = _downsample_loudness_db(np.zeros(50))   # log10(0) would be -inf
    assert np.all(np.isfinite(db)) and np.all(db < -90)


def test_downsample_empty_input():
    assert _downsample_loudness_db(np.array([])).size == 0


def test_extract_produces_a_plausible_curve():
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=5.0)
    tf = extract_features(sig)
    pts = tf.loudness_curve_points()
    assert pts is not None and 2 <= len(pts) <= LOUDNESS_CURVE_POINTS
    assert all(math.isfinite(v) for v in pts)
    assert all(-100.0 <= v <= 0.0 for v in pts)  # dBFS: normalized audio can't exceed 0
    # display-only: the curve must NOT contaminate the vector or the summary dict
    assert "loudness_curve" not in tf.to_summary_dict()
    assert len(tf.to_summary_vector()) == 77
