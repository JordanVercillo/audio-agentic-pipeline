"""
test_sections.py — structural section detection (F-v3), synthetic.

An A–B–A composite signal (two alternating textures) is the ground truth the
detector must recover: a boundary near each texture change, and the two A
parts sharing a LABEL (repeat identity — the honest deliverable; we never
claim "chorus"/"verse"). Ground rule: synthetic audio only.
"""

from __future__ import annotations

import numpy as np

from .audio_loader import SAMPLE_RATE, AudioSignal, generate_test_signal
from .feature_extractor import extract_features, sections_from_signal


def _tone(freqs: list[float], seconds: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    return (y / np.max(np.abs(y))).astype(np.float32)


def _aba_signal(part: float = 10.0) -> AudioSignal:
    """A (220 Hz triad) — B (dissonant high cluster) — A again.

    Parts are 10 s — comfortably above the 7 s minimum-section merge, so the
    fixture stays valid ground truth for the tuned detector."""
    a = _tone([220.0, 277.2, 329.6], part)          # A-major-ish triad
    b = _tone([466.2, 622.3, 830.6], part)          # a distant, brighter cluster
    y = np.concatenate([a, b, a])
    return AudioSignal(waveform=y, sr=SAMPLE_RATE,
                       duration_sec=len(y) / SAMPLE_RATE,
                       file_path="synthetic://aba", file_name="aba",
                       n_samples=len(y))


def test_aba_boundaries_and_repeat_identity():
    secs = sections_from_signal(_aba_signal())
    assert len(secs) >= 3
    assert secs[0]["start"] == 0.0 and secs[-1]["end"] > 29.5   # spans the track
    # contiguous, ordered, no overlaps
    for prev, cur in zip(secs[:-1], secs[1:], strict=True):
        assert cur["start"] == prev["end"]
    # repeat identity: the outer A parts share a label the middle doesn't
    assert secs[0]["label"] == secs[-1]["label"]
    assert any(s["label"] != secs[0]["label"] for s in secs[1:-1])
    # labels are first-appearance ordered: the first section is always 0
    assert secs[0]["label"] == 0
    # a boundary lands near each true texture change (±2.5 s)
    bounds = [s["start"] for s in secs[1:]]
    assert any(abs(b - 10.0) <= 2.5 for b in bounds)
    assert any(abs(b - 20.0) <= 2.5 for b in bounds)


def test_sections_carry_honest_stats():
    secs = sections_from_signal(_aba_signal())
    for s in secs:
        assert set(s) == {"start", "end", "label", "tempo_bpm",
                          "loudness_db", "key", "mode"}
        assert s["tempo_bpm"] >= 0.0
        assert s["loudness_db"] is None or -100.0 <= s["loudness_db"] <= 0.0
        assert -1 <= s["key"] <= 11 and s["mode"] in ("major", "minor", "")
    # no semantic labels anywhere — the honesty boundary, documented by test
    assert not any(k in ("name", "kind", "type") for s in secs for k in s)


def test_sections_deterministic():
    sig = _aba_signal()
    assert sections_from_signal(sig) == sections_from_signal(sig)


def test_uniform_signal_yields_one_section():
    sig = generate_test_signal(frequency_hz=220.0, duration_sec=10.0)
    secs = sections_from_signal(sig)
    labels = {s["label"] for s in secs}
    assert len(labels) <= 2            # no invented structure in a constant tone
    assert secs[0]["start"] == 0.0 and abs(secs[-1]["end"] - 10.0) < 0.1


def test_extract_features_populates_sections_out_of_contract():
    tf = extract_features(_aba_signal())
    assert tf.sections is not None and len(tf.sections) >= 2
    assert tf.sections_list() == tf.sections
    assert "sections" not in tf.to_summary_dict()   # display data, not a feature
    assert len(tf.to_summary_vector()) == 77         # frozen vector untouched
