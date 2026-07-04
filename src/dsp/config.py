"""
config.py — Canonical DSP Parameters (Single Source of Truth)
=============================================================
Every DSP constant used across the pipeline is defined here.
These values enforce dimensional consistency so that all feature
matrices, embeddings, and ML inputs share identical time/frequency
resolution regardless of which module produced them.

Reference: 02_audio_dsp_architect.md
"""

from dataclasses import dataclass, field
from enum import Enum

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CANONICAL CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# -- Sample Rates --
# 22050 Hz: Nyquist theorem guarantees we capture frequencies up to ~11 kHz.
# Music fundamentals (vocals, most instruments) sit below 8 kHz, so 22050 Hz
# is the industry standard for MIR without wasting compute on inaudible content.
SAMPLE_RATE: int = 22050

# 16000 Hz: Required input sample rate for VGGish and many environmental
# sound classification models. Only use when feeding into those specific models.
SAMPLE_RATE_VGGISH: int = 16000

# -- STFT (Short-Time Fourier Transform) Window --
# n_fft = 2048 samples → ~93ms analysis window at 22050 Hz.
# This is long enough to resolve bass fundamentals (frequency resolution
# = sr / n_fft = 22050 / 2048 ≈ 10.77 Hz per bin) while short enough
# to capture transient attacks in drums/percussion.
N_FFT: int = 2048

# hop_length = 512 samples → ~23ms hop between consecutive STFT frames.
# This gives us 75% overlap with the n_fft window (512 / 2048 = 0.25),
# producing ~43 frames per second — smooth enough for beat tracking
# and onset detection without being wastefully dense.
HOP_LENGTH: int = 512

# -- Mel Filterbank --
# 128 mel bands: standard resolution that balances perceptual frequency
# detail with computational cost. Matches the input expectations of
# PANNs (Cnn14) and most pre-trained audio classifiers.
N_MELS: int = 128

# -- MFCCs --
# 13 coefficients: the classic choice from speech processing (Davis & Mermelstein, 1980).
# Coefficients 1-13 capture the spectral envelope (timbre, vowel quality).
# Higher coefficients model fine spectral detail that adds noise for most
# music classification tasks. Coefficient 0 (energy) is included.
N_MFCC: int = 13

# -- Amplitude Normalization --
# top_db = 80 dB: clips the dynamic range floor when converting power
# spectrograms to decibel scale via librosa.power_to_db(). Anything
# quieter than -80 dB relative to peak is treated as silence. This
# prevents log(0) explosions and normalizes the feature range for neural nets.
TOP_DB: float = 80.0

# -- Audio Validation Thresholds --
MIN_DURATION_SEC: float = 1.0    # Reject files shorter than 1 second
MAX_DURATION_SEC: float = 600.0  # Warn on files longer than 10 minutes (memory guard)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEATURE GROUPS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FeatureGroup(Enum):
    """
    Logical groupings of audio features.
    Used to selectively extract subsets of the full feature pipeline.
    """
    RHYTHM = "rhythm"          # tempo, onset_strength, beat positions
    TIMBRE = "timbre"          # MFCCs, spectral centroid, contrast, rolloff
    TONAL = "tonal"            # chroma (HPCP), estimated key/mode
    ENERGY = "energy"          # RMS energy, zero crossing rate
    SPECTRAL = "spectral"      # mel spectrogram (2D matrix)
    ALL = "all"                # extract everything


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RUNTIME CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class DSPConfig:
    """
    Runtime-configurable DSP parameters. Defaults mirror the canonical
    constants above. Override only when you have a specific reason
    (e.g., feeding a model trained at 16000 Hz).
    """
    sr: int = SAMPLE_RATE
    n_fft: int = N_FFT
    hop_length: int = HOP_LENGTH
    n_mels: int = N_MELS
    n_mfcc: int = N_MFCC
    top_db: float = TOP_DB
    mono: bool = True
    feature_groups: list[FeatureGroup] = field(
        default_factory=lambda: [FeatureGroup.ALL]
    )

    def should_extract(self, group: FeatureGroup) -> bool:
        """Check whether a specific feature group is enabled."""
        return FeatureGroup.ALL in self.feature_groups or group in self.feature_groups
