"""
audio_loader.py — Audio I/O, Resampling & Validation
=====================================================
Handles all audio file loading with strict enforcement of canonical
DSP parameters. Every audio file that enters this pipeline goes
through the same normalization gate:
    1. Resample to 22050 Hz (or configured sr)
    2. Downmix to mono
    3. Peak-normalize to [-1.0, 1.0]
    4. Validate duration bounds

Reference: 02_audio_dsp_architect.md — "Resample immediately upon load"
"""

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np

try:
    import librosa
except ImportError:
    raise ImportError(
        "librosa is required for audio loading. Install via: pip install librosa>=0.10.0"
    )

from .config import DSPConfig, SAMPLE_RATE, MIN_DURATION_SEC, MAX_DURATION_SEC


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA STRUCTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AudioSignal:
    """
    Standardized container for a loaded audio signal.
    All downstream DSP modules consume this dataclass — never raw
    numpy arrays — so we always carry the metadata needed to
    interpret the waveform correctly.
    """
    waveform: np.ndarray   # 1D float32, peak-normalized to [-1.0, 1.0]
    sr: int                # Sample rate in Hz
    duration_sec: float    # Duration in seconds
    file_path: str         # Original path for provenance tracking
    file_name: str         # Stem without extension
    n_samples: int         # len(waveform)


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CORE LOADING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_audio(
    file_path: Union[str, Path],
    config: Optional[DSPConfig] = None,
) -> AudioSignal:
    """
    Load an audio file into a standardized AudioSignal.

    Steps: validate → librosa.load (resample + mono) → duration check → peak-normalize.

    Peak normalization happens here (not downstream) because raw amplitude varies
    wildly across sources. Normalizing at load ensures consistent dynamic range for
    all features (STFT, RMS, MFCCs).
    """
    if config is None:
        config = DSPConfig()

    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported format: '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # sr=config.sr forces resampling; mono=True downmixes by averaging channels
    y, sr = librosa.load(str(path), sr=config.sr, mono=config.mono)
    duration_sec = len(y) / sr

    if duration_sec < MIN_DURATION_SEC:
        raise ValueError(f"Audio too short: {duration_sec:.2f}s (min: {MIN_DURATION_SEC}s)")
    if duration_sec > MAX_DURATION_SEC:
        warnings.warn(
            f"⚠️  Long file: {duration_sec:.1f}s — may use significant memory. "
            f"Consider essentia streaming mode for production. File: {path.name}",
            UserWarning, stacklevel=2,
        )

    y = _peak_normalize(y)

    return AudioSignal(
        waveform=y, sr=sr, duration_sec=duration_sec,
        file_path=str(path), file_name=path.stem, n_samples=len(y),
    )


def load_audio_batch(
    directory: Union[str, Path],
    config: Optional[DSPConfig] = None,
    recursive: bool = False,
) -> list[AudioSignal]:
    """Load all supported audio files from a directory. Failures are skipped with warnings."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    pattern_fn = directory.rglob if recursive else directory.glob
    audio_files = sorted(
        f for f in pattern_fn("*")
        if f.suffix.lower() in SUPPORTED_EXTENSIONS and f.is_file()
    )

    if not audio_files:
        warnings.warn(f"No audio files found in: {directory}", UserWarning, stacklevel=2)
        return []

    signals = []
    for i, fp in enumerate(audio_files):
        try:
            sig = load_audio(fp, config=config)
            signals.append(sig)
            print(f"   ✅ [{i+1}/{len(audio_files)}] {fp.name} ({sig.duration_sec:.1f}s)")
        except (ValueError, FileNotFoundError) as e:
            print(f"   ⚠️  [{i+1}/{len(audio_files)}] Skipped: {fp.name} — {e}")

    print(f"\n   📂 Loaded {len(signals)}/{len(audio_files)} files")
    return signals


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SYNTHETIC SIGNAL (for testing)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_test_signal(
    frequency_hz: float = 440.0,
    duration_sec: float = 5.0,
    sr: int = SAMPLE_RATE,
    amplitude: float = 0.8,
) -> AudioSignal:
    """Generate a synthetic sine wave for pipeline smoke testing."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    y = amplitude * np.sin(2 * np.pi * frequency_hz * t).astype(np.float32)

    return AudioSignal(
        waveform=y, sr=sr, duration_sec=duration_sec,
        file_path="<synthetic>",
        file_name=f"sine_{frequency_hz}hz_{duration_sec}s",
        n_samples=len(y),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _peak_normalize(y: np.ndarray) -> np.ndarray:
    """
    Normalize so absolute peak = 1.0. Preserves dynamic range and transient
    structure (unlike RMS normalization which can clip). Returns silence as-is.
    """
    peak = np.max(np.abs(y))
    if peak < 1e-8:
        return y
    return y / peak
