"""P4.7.0 — the one-registry guarantees.

Three files described the same six DSP columns with three vocabularies, and one
of them disagreed in a way a visitor could see: `rms_mean` was "Loudness" in the
σ-signature and "Energy" in the absolute profile, while the perceptual catalog
carries a SEPARATE derived `energy`. These tests make that class of drift fail
in CI instead of on the page — before Epic R doubles the consumers.

Synthetic only.
"""
from __future__ import annotations

from ..analysis.clustering import _CHARACTER_DIMS
from . import scales
from .analytics import _SIGNATURE_DIMS
from .taste import _BANDS


def test_every_column_has_exactly_one_display_name():
    """The bug this slice exists to kill: one column, two visitor-facing names."""
    seen: dict[str, set[str]] = {}
    for col, name, *_ in _SIGNATURE_DIMS:
        seen.setdefault(col, set()).add(name)
    for col, (name, _unit, _b) in _BANDS.items():
        seen.setdefault(col, set()).add(name)
    clashes = {c: names for c, names in seen.items() if len(names) > 1}
    assert not clashes, f"a column is called two different things: {clashes}"


def test_rms_mean_is_not_called_energy():
    """`energy` is a DIFFERENT, derived feature in the perceptual catalog (a
    blend of RMS + onset + rolloff) with its own `loudness_db` beside it. Naming
    the raw RMS column "Energy" made one word mean two numbers across pages."""
    from ..store.perceptual import CATALOG

    catalog_cols = {c["column"] for c in CATALOG}
    assert "energy" in catalog_cols and "loudness_db" in catalog_cols
    assert scales.display_name("rms_mean") == "Loudness"
    for _col, (name, _u, _b) in _BANDS.items():
        assert name != "Energy", "the raw RMS column is labelled Energy again"


def test_consumers_derive_from_the_registry_not_their_own_copy():
    assert _SIGNATURE_DIMS == scales.signature_dims()
    assert _BANDS == scales.bands()


def test_character_words_are_imported_never_restated():
    """Cluster labels ARE identities a visitor has seen (D-62): a retyped word
    is a rename, and a rename fails the identity-stable promotion gate. So the
    registry must hand back clustering's own list, order included."""
    assert scales.character_dims() == list(_CHARACTER_DIMS)
    # and the frozen content itself, so a careless edit upstream is visible here
    assert _CHARACTER_DIMS[0] == ("rms_mean", "Loud", "Quiet")
    assert [c for c, *_ in _CHARACTER_DIMS] == [
        "rms_mean", "tempo_bpm", "harmonic_ratio", "spectral_centroid_mean",
        "zcr_mean", "onset_strength_mean"]


def test_band_words_are_ordered_and_reachable():
    """Every band must be reachable — an unordered or mis-bounded list silently
    makes a word unreachable, so a visitor never sees it."""
    for col, (_name, _unit, band_list) in scales.bands().items():
        uppers = [u for u, _w in band_list]
        assert uppers == sorted(uppers), f"{col} bands are not ascending"
        assert band_list[-1][0] >= 1e9, f"{col} has no catch-all band"
        words = set()
        probe = -1e6
        for upper, _word in band_list:
            mid = probe if upper >= 1e9 else (probe + upper) / 2
            words.add(scales.band_word(mid, band_list))
            probe = upper
        assert len(words) == len(band_list), f"{col}: a band word is unreachable"


def test_signature_and_character_agree_on_which_columns_are_interpretable():
    """The two vocabularies may use different WORDS, but they must not disagree
    about which columns a human can be told about."""
    sig = {c for c, *_ in _SIGNATURE_DIMS}
    char = {c for c, *_ in scales.character_dims()}
    assert char <= sig, f"cluster names use columns the signature won't explain: {char - sig}"
