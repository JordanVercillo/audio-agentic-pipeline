"""D-66 — the transparency contract, enforced against the LIVE extractor.

"All the features" is a claim. These tests make it checkable: every numeric
column the extractor emits must be documented, and nothing may be documented
that the extractor no longer emits. Both directions matter — the first catches
"we added an 84th feature and the page shows a bare float", the second catches
"we deleted one and the page still describes it".

Re-derived through `extract_features(generate_test_signal())`, so the guard
tracks the code rather than a hand-kept roster. Synthetic only (ground rule 5).
"""
from __future__ import annotations

import pytest

from .audio_loader import generate_test_signal
from .feature_doc import (
    RAW_FEATURE_DOC,
    RAW_FEATURE_NON_NUMERIC,
    RAW_FEATURE_PROMOTED,
    doc_for,
    documented_columns,
)
from .feature_extractor import extract_features


@pytest.fixture(scope="module")
def summary() -> dict:
    return extract_features(generate_test_signal()).to_summary_dict()


def test_every_numeric_feature_is_documented(summary):
    numeric = {k for k, v in summary.items() if isinstance(v, (int, float))}
    undocumented = sorted(c for c in numeric if not doc_for(c))
    assert not undocumented, (
        f"{len(undocumented)} feature(s) would render as a bare number with no "
        f"explanation: {undocumented[:10]}")


def test_no_documented_family_is_orphaned(summary):
    """The other direction: a family nothing produces any more is a lie the
    page would keep telling."""
    keys = set(summary)
    for base in RAW_FEATURE_DOC:
        family = base[5:] if base.startswith("base_") else base
        matched = [k for k in keys if k == family or k.startswith(family + "_")]
        assert matched, f"documented '{base}' matches nothing the extractor emits"


def test_every_key_is_accounted_for(summary):
    """No key may be silently ignored — each is a feature, a known non-numeric,
    or a bug."""
    for key, value in summary.items():
        if key in RAW_FEATURE_NON_NUMERIC:
            continue
        assert isinstance(value, (int, float)), f"unexpected non-numeric key {key}"
        assert doc_for(key), f"{key} is neither documented nor a known non-feature"


def test_indexed_families_resolve_to_one_entry(summary):
    """13 MFCC coefficients documented once, not thirteen times."""
    assert doc_for("mfcc_mean_0") is doc_for("mfcc_mean_12")
    assert doc_for("chroma_mean_C") is doc_for("chroma_mean_F#")
    assert doc_for("spectral_contrast_mean_0") is doc_for("spectral_contrast_mean_6")
    assert "not interpretable in isolation" in doc_for("mfcc_mean_3")["caveat"]


def test_categorical_columns_are_flagged_as_unorderable(summary):
    """A percentile on a pitch class is nonsense; the renderer keys off this."""
    assert "categorical" in doc_for("estimated_key")["direction"]


def test_documented_columns_is_driven_by_the_live_keys(summary):
    numeric = [k for k, v in summary.items() if isinstance(v, (int, float))]
    got = documented_columns(numeric)
    assert set(got) == set(numeric)
    assert all(e for e in got.values())


def test_promoted_columns_are_named_and_are_not_in_the_dict(summary):
    """`loudness_curve` & co. are stored and shown but sit OUTSIDE the 82-col
    contract. Naming them is how the page can claim "all the features" without
    a visitor who counts finding a discrepancy."""
    for col in RAW_FEATURE_PROMOTED:
        assert col not in summary, f"{col} leaked into the feature dict"
    assert len(RAW_FEATURE_PROMOTED) >= 4


def test_the_headline_count_is_what_we_claim(summary):
    """The page says "all 83". If the extractor changes, this is the test that
    makes someone update the sentence instead of shipping a wrong number."""
    numeric = [k for k, v in summary.items() if isinstance(v, (int, float))]
    assert len(numeric) == 83, (
        f"the feature count changed to {len(numeric)} — update the "
        f"/song/{{id}}/features copy and this assertion together")
