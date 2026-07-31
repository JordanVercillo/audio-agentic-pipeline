"""
feature_doc.py — plain-language meaning for every column the extractor emits.

D-66 / Vision F P4.7.1. `/song/{id}/features` shows all 83 numeric features, and
a description written in a Jinja template would be a SECOND ENCODING of what the
DSP layer means by a column: retune an estimator and the webapp silently starts
lying (journal #27). So the dictionary lives HERE, beside the extractor that
produces the values, and travels to the webapp as a mart —
`build_feature_marts` writes `raw_feature_dictionary.parquet`, the webapp only
reads it.

Indexed families (mfcc_mean_0…12, chroma_mean_C…B, spectral_contrast_*_0…6) are
documented ONCE by a `base_*` key and expanded at build time. A set-equality
test re-derives the documented set through the LIVE extractor, so an 84th
feature cannot ship undocumented and a deleted one cannot linger as a lie.

`direction` reads a HIGH value. "categorical — no order" means a percentile is
meaningless and must not be rendered.
"""
from __future__ import annotations

# ── the dictionary ──────────────────────────────────────────────────────────
RAW_FEATURE_DOC: dict[str, dict[str, str]] = {
    # ── time & rhythm ───────────────────────────────────────────────────────
    "duration_sec": dict(
        group="Time & rhythm", unit="s", direction="longer",
        desc="Length of the audio analysed."),
    "tempo_bpm": dict(
        group="Time & rhythm", unit="bpm", direction="faster",
        desc="Estimated beats per minute of the main pulse.",
        caveat="Quantised to librosa's tempogram lag grid — the corpus takes "
               "only about 20 distinct values, so small differences between "
               "tracks are not meaningful."),
    "beat_count": dict(
        group="Time & rhythm", unit="beats", direction="more",
        desc="How many beats were detected across the whole track."),
    "beats_per_sec": dict(
        group="Time & rhythm", unit="/s", direction="denser",
        desc="Beat density — beats detected per second. Reads lower than tempo "
             "when a track has sparse or silent stretches."),
    "onset_strength_mean": dict(
        group="Time & rhythm", unit="", direction="punchier",
        desc="Average strength of note attacks — how sharply new sounds begin."),
    "onset_strength_std": dict(
        group="Time & rhythm", unit="", direction="more varied",
        desc="How much attack strength varies over the track."),

    # ── level & dynamics ────────────────────────────────────────────────────
    "rms_mean": dict(
        group="Level & dynamics", unit="", direction="louder",
        desc="Average signal level (RMS).",
        caveat="Audio is peak-normalised at load, so this is level RELATIVE to "
               "the track's own peak — not absolute loudness, and not "
               "comparable to a mastering LUFS figure."),
    "rms_std": dict(
        group="Level & dynamics", unit="", direction="more dynamic",
        desc="How much the level moves — high means quiet and loud passages, "
             "low means a steady wall of sound."),

    # ── spectral shape ──────────────────────────────────────────────────────
    "spectral_centroid_mean": dict(
        group="Spectral shape", unit="Hz", direction="brighter",
        desc="The centre of gravity of the spectrum — the usual proxy for "
             "brightness."),
    "spectral_centroid_std": dict(
        group="Spectral shape", unit="Hz", direction="more varied",
        desc="How much that brightness moves over time."),
    "spectral_rolloff_mean": dict(
        group="Spectral shape", unit="Hz", direction="airier",
        desc="The frequency below which most of the energy sits — how far the "
             "treble reaches."),
    "spectral_rolloff_std": dict(
        group="Spectral shape", unit="Hz", direction="more varied",
        desc="Variation in that treble reach."),
    "spectral_bandwidth_mean": dict(
        group="Spectral shape", unit="Hz", direction="wider",
        desc="How spread out the spectrum is around its centre."),
    "spectral_bandwidth_std": dict(
        group="Spectral shape", unit="Hz", direction="more varied",
        desc="Variation in that spread."),
    "spectral_flatness_mean": dict(
        group="Spectral shape", unit="", direction="noisier",
        desc="Noise-versus-tone balance: near 1 is noise-like, near 0 is pitched."),
    "zcr_mean": dict(
        group="Spectral shape", unit="", direction="noisier",
        desc="Zero-crossing rate — how often the waveform changes sign. High "
             "for cymbals, distortion and sibilance."),
    "zcr_std": dict(
        group="Spectral shape", unit="", direction="more varied",
        desc="Variation in that crossing rate."),
    "harmonic_ratio": dict(
        group="Spectral shape", unit="", direction="more harmonic",
        desc="The share of the signal that separates out as harmonic rather "
             "than percussive."),

    # ── timbre fingerprint ──────────────────────────────────────────────────
    "base_mfcc_mean": dict(
        group="Timbre fingerprint", unit="", direction="—",
        desc="Mel-frequency cepstral coefficients — a compact description of "
             "spectral SHAPE, which is what we hear as timbre.",
        caveat="Individual coefficients are not interpretable in isolation. The "
               "shape ACROSS them is the fingerprint, and it is what "
               "'songs like this' compares."),
    "base_mfcc_std": dict(
        group="Timbre fingerprint", unit="", direction="—",
        desc="How much each timbral coefficient varies over the track.",
        caveat="Not interpretable coefficient by coefficient."),
    "base_spectral_contrast_mean": dict(
        group="Timbre fingerprint", unit="dB", direction="—",
        desc="Peak-to-valley difference within each of seven frequency bands — "
             "how sharply each band separates foreground from background."),
    "base_spectral_contrast_std": dict(
        group="Timbre fingerprint", unit="dB", direction="—",
        desc="Variation in that band contrast."),

    # ── tonal & harmony ─────────────────────────────────────────────────────
    "estimated_key": dict(
        group="Tonal & harmony", unit="pitch class",
        direction="categorical — no order",
        desc="Detected tonic as a pitch class (0=C, 1=C#, … 11=B).",
        caveat="A percentile is meaningless for a pitch class, so none is shown."),
    "base_chroma_mean": dict(
        group="Tonal & harmony", unit="", direction="—",
        desc="Average strength of each of the twelve pitch classes, ignoring "
             "octave — the track's harmonic profile."),
    "base_chroma_std": dict(
        group="Tonal & harmony", unit="", direction="—",
        desc="How much each pitch class's strength varies over the track."),
}

# Emitted by to_summary_dict() but NOT features: identifiers and the one string
# label. Named so the set-equality test accounts for every key rather than
# quietly ignoring the ones it finds inconvenient.
RAW_FEATURE_NON_NUMERIC = ("file_name", "file_path", "estimated_mode")

# Stored per track and shown on /song, but deliberately OUTSIDE the 82-col dict
# and the frozen 77-dim vector (F-v2/F-v3, journal #18). Named here because
# "all the features" is a claim: a visitor who counts should find the honest
# answer, not a discrepancy.
RAW_FEATURE_PROMOTED = ("loudness_curve", "beat_times", "sections",
                        "time_signature", "match_confidence")

_BASE_PREFIX = "base_"


def doc_for(column: str) -> dict[str, str]:
    """The dictionary entry for a concrete column, resolving indexed families.

    `mfcc_mean_7` and `chroma_mean_F#` resolve to their family entry, so a
    13-coefficient family is documented once rather than thirteen times.
    """
    if column in RAW_FEATURE_DOC:
        return RAW_FEATURE_DOC[column]
    for base, entry in RAW_FEATURE_DOC.items():
        if not base.startswith(_BASE_PREFIX):
            continue
        family = base[len(_BASE_PREFIX):]
        if column.startswith(family + "_"):
            return entry
    return {}


def documented_columns(actual: list[str]) -> dict[str, dict[str, str]]:
    """{column: entry} for every column the extractor actually produced.

    Driven by the LIVE key list rather than a hand-kept roster, so the mart can
    never claim a column the extractor stopped emitting.
    """
    return {c: doc_for(c) for c in actual}
