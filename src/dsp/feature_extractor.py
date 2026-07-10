"""
feature_extractor.py — Core DSP Feature Extraction Pipeline
============================================================
Extracts everything Spotify's deprecated /audio-features provided, plus more.
This module fills the acoustic intelligence gap left by the Feb 2026 API changes.

Feature Map (What We Extract → What It Replaces):
    ┌──────────────────────┬───────────────────────────────────────┐
    │ Our Feature          │ Replaces Spotify's...                 │
    ├──────────────────────┼───────────────────────────────────────┤
    │ Tempo (BPM)          │ tempo                                 │
    │ RMS Energy           │ energy                                │
    │ Spectral Centroid    │ brightness proxy                      │
    │ Zero Crossing Rate   │ speechiness / noisiness proxy         │
    │ MFCCs (13 coeff.)    │ timbral fingerprint (no equivalent)   │
    │ Chroma (HPCP)        │ key, mode                             │
    │ Mel Spectrogram      │ deep learning input tensor            │
    │ Spectral Contrast    │ harmonic vs. noise ratio              │
    │ Spectral Rolloff     │ frequency ceiling (brightness proxy)  │
    │ Onset Strength       │ danceability proxy (rhythmic energy)  │
    │ Harmonic Ratio       │ acousticness proxy                    │
    └──────────────────────┴───────────────────────────────────────┘

Output Formats:
    1. Summary vector (1D): Time-axis aggregated (mean + std) → flat row for ML
    2. Full matrix (2D): Raw time-series → for deep learning / visualization

Reference: 02_audio_dsp_architect.md
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import librosa
except ImportError:
    raise ImportError("librosa is required. Install: pip install librosa>=0.10.0") from None

from .audio_loader import AudioSignal
from .config import DSPConfig, FeatureGroup

# The loudness curve is fixed-length so every song's chart is the same width and
# comparable, regardless of duration (longer songs → coarser time bins).
LOUDNESS_CURVE_POINTS = 120
_LOUDNESS_FLOOR = 1e-5  # RMS floor → ~-100 dBFS for silence (avoids log10(0))


def loudness_curve_from_signal(signal: AudioSignal, config: Optional[DSPConfig] = None) -> list[float]:
    """Just the loudness curve (dBFS points) from a signal — the cheap path for
    backfilling existing local audio without a full extraction (RMS only, no
    HPSS/MFCC). Identical downsampling to the in-extractor curve, so a backfilled
    track matches what a fresh extraction would produce."""
    if config is None:
        config = DSPConfig()
    rms = librosa.feature.rms(
        y=signal.waveform, frame_length=config.n_fft, hop_length=config.hop_length)[0]
    return [round(float(v), 2) for v in _downsample_loudness_db(rms)]


def time_signature_from_signal(signal: AudioSignal, config: Optional[DSPConfig] = None) -> int:
    """Estimate the meter from a signal — the cheap path for backfilling existing
    local audio (onset + beat tracking only, no MFCC/HPSS/chroma). Same estimator
    the extractor runs, so a backfilled meter matches a fresh extraction."""
    if config is None:
        config = DSPConfig()
    onset_env = librosa.onset.onset_strength(
        y=signal.waveform, sr=signal.sr, hop_length=config.hop_length)
    _tempo, beat_frames = librosa.beat.beat_track(
        y=signal.waveform, sr=signal.sr, hop_length=config.hop_length,
        onset_envelope=onset_env)
    return _estimate_time_signature(onset_env, beat_frames)


def beat_grid_from_signal(signal: AudioSignal, config: Optional[DSPConfig] = None) -> list[float]:
    """Just the detected beat times (seconds) from a signal — the cheap path for
    backfilling the beat grid (F-v2c) from existing local audio (onset + beat
    tracking only)."""
    if config is None:
        config = DSPConfig()
    onset_env = librosa.onset.onset_strength(
        y=signal.waveform, sr=signal.sr, hop_length=config.hop_length)
    _tempo, beat_frames = librosa.beat.beat_track(
        y=signal.waveform, sr=signal.sr, hop_length=config.hop_length,
        onset_envelope=onset_env)
    return [round(float(t), 2)
            for t in librosa.frames_to_time(beat_frames, sr=signal.sr, hop_length=config.hop_length)]


# Candidate meters (beats per bar) to test. We start at 3, NOT 2: a 4/4 song
# with a backbeat (accents on 1 AND 3) has period-2 accent structure, so lag-2
# autocorrelation competes with lag-4 and would mislabel most 4/4 as 2/4. Duple
# meter is genuinely ambiguous from accents alone and real 2/4 is vanishingly
# rare, so duple collapses to the 4 default; the estimator's job is to surface
# the ODD/compound meters (3, 5, 6, 7). Weak evidence also falls back to 4.
_METER_CANDIDATES = range(3, 8)
_METER_DEFAULT = 4
_METER_MIN_CORR = 0.10


def _estimate_time_signature(onset_env: np.ndarray, beat_frames: np.ndarray) -> int:
    """Estimate beats-per-bar from the periodicity of beat accents.

    Sample the onset-strength envelope at each detected beat, then autocorrelate
    that per-beat accent signal: the lag whose accents best repeat is the bar
    length (downbeats recur every N beats). Honest and coarse — weak evidence or
    too few beats returns 4 (common time), never a fabricated exotic meter.
    """
    if beat_frames is None or len(beat_frames) < 8 or onset_env.size == 0:
        return _METER_DEFAULT
    idx = np.clip(np.asarray(beat_frames), 0, onset_env.size - 1)
    accents = onset_env[idx].astype(float)
    accents = accents - accents.mean()
    if accents.std() < 1e-8:
        return _METER_DEFAULT
    best_lag, best_corr = _METER_DEFAULT, -np.inf
    for lag in _METER_CANDIDATES:
        if lag >= accents.size:
            break
        a, b = accents[:-lag], accents[lag:]
        if a.std() < 1e-8 or b.std() < 1e-8:
            continue
        corr = float(np.corrcoef(a, b)[0, 1])
        if corr > best_corr:
            best_corr, best_lag = corr, lag
    return int(best_lag) if best_corr >= _METER_MIN_CORR else _METER_DEFAULT


# ── structural sections (F-v3) ───────────────────────────────────────────────
# Simplified Laplacian structure segmentation (McFee & Ellis 2014): a
# path-enhanced recurrence graph on beat-synced CHROMA captures "this part
# sounds like that part" (harmony repeats); a path graph on local MFCC
# continuity keeps segments contiguous; the normalized Laplacian's leading
# eigenvectors embed frames so KMeans groups them into section TYPES. The
# eigengap picks how many types the song actually supports (2..6).
_SECTION_K_MAX = 6
# Tuned on the real corpus (journal #21: check the DISTRIBUTION, not just the
# unit tests): with 3 s minimums + light smoothing, 20/117 tracks fragmented
# into 25–63 "sections" — label ping-pong, not structure. Musical sections run
# ~8 s and up, so blips under 7 s merge and labels smooth over ~9 beats.
_SECTION_MIN_SEC = 7.0        # merge spans shorter than this into a neighbor
_SECTION_SMOOTH = 9           # median-filter width over per-beat labels (~5 s)
_SECTION_MIN_FRAMES = 12      # too little structure to segment → one section


def _section_labels(rec_feats: np.ndarray, path_feats: np.ndarray,
                    k_max: int = _SECTION_K_MAX) -> np.ndarray:
    """Per-frame section-type labels (same label = same-sounding part)."""
    from scipy.ndimage import median_filter
    from scipy.sparse import diags
    from scipy.sparse.csgraph import laplacian
    from sklearn.cluster import KMeans

    n = rec_feats.shape[1]
    if n < _SECTION_MIN_FRAMES:
        return np.zeros(n, dtype=int)

    rec = librosa.segment.recurrence_matrix(
        rec_feats, width=3, mode="affinity", sym=True)
    rec = librosa.segment.path_enhance(rec, 7)

    # Local-continuity path graph from timbre distance between adjacent frames.
    dist = np.sum(np.diff(path_feats, axis=1) ** 2, axis=0)
    sim = np.exp(-dist / (np.median(dist) + 1e-9))
    path = diags([sim, sim], [1, -1], shape=(n, n)).toarray()

    # Degree-balanced combination (the paper's mu), then the spectral embedding.
    deg_path, deg_rec = path.sum(axis=1), rec.sum(axis=1)
    denom = float(np.sum((deg_path + deg_rec) ** 2)) + 1e-12
    mu = float(deg_path.dot(deg_path + deg_rec)) / denom
    lap = laplacian(mu * rec + (1 - mu) * path, normed=True)
    evals, evecs = np.linalg.eigh(lap)

    ks = np.arange(2, min(k_max, n - 1) + 1)
    k = int(ks[np.argmax(evals[ks] - evals[ks - 1])])  # eigengap heuristic
    emb = librosa.util.normalize(evecs[:, :k], norm=2, axis=1)
    labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(emb)
    return median_filter(labels, size=_SECTION_SMOOTH, mode="nearest")


def _assemble_sections(labels: np.ndarray, frame_times: np.ndarray,
                       chroma_sync: np.ndarray, beat_times: np.ndarray,
                       duration: float, loudness_curve: Optional[np.ndarray],
                       ) -> list[dict]:
    """Contiguous same-label runs → section dicts with honest per-section stats.

    Stats come from data already computed: tempo = beat density inside the
    section, loudness = the stored curve's points inside it, key/mode = the
    section's mean chroma through the same Krumhansl-Kessler estimator.
    """
    # label runs → (first_frame, end_frame_exclusive) spans
    spans: list[list[int]] = []
    for i, lab in enumerate(labels):
        if spans and labels[spans[-1][0]] == lab:
            spans[-1][1] = i + 1
        else:
            spans.append([i, i + 1])

    # merge sub-minimum blips into the previous span (the first into the next)
    def _span_dur(s: list[int]) -> float:
        start = 0.0 if s[0] == 0 else float(frame_times[s[0]])
        end = duration if s[1] >= len(labels) else float(frame_times[s[1]])
        return end - start

    # A span's identity is its MAJORITY label (blip absorption means the first
    # frame's label can misrepresent the span).
    def _span_label(s: list[int]) -> int:
        return int(np.bincount(labels[s[0]:s[1]]).argmax())

    merged: list[list[int]] = []
    for s in spans:
        if merged and _span_dur(s) < _SECTION_MIN_SEC:
            merged[-1][1] = s[1]        # absorb the blip backward
        else:
            merged.append(s)
    # The opening span can't merge backward — fold it forward instead
    # (majority labeling keeps the survivor's identity honest).
    if len(merged) > 1 and _span_dur(merged[0]) < _SECTION_MIN_SEC:
        merged[1][0] = merged[0][0]
        merged.pop(0)

    # Coalesce adjacent SAME-label spans (absorption can leave A|A neighbors —
    # a boundary between two identical sections is noise, not structure).
    coalesced: list[list[int]] = []
    for s in merged:
        if coalesced and _span_label(coalesced[-1]) == _span_label(s):
            coalesced[-1][1] = s[1]
        else:
            coalesced.append(s)
    merged = coalesced

    # letters by first appearance — A is the first sound heard, not "verse"
    relabel: dict[int, int] = {}
    out: list[dict] = []
    for s in merged:
        lab = _span_label(s)
        relabel.setdefault(lab, len(relabel))
        start = 0.0 if s is merged[0] else float(frame_times[s[0]])
        end = duration if s is merged[-1] else float(frame_times[min(s[1], len(frame_times) - 1)])
        if end <= start:
            continue
        n_beats = int(np.sum((beat_times >= start) & (beat_times < end)))
        tempo = 60.0 * n_beats / (end - start) if end > start else 0.0
        loud = None
        if loudness_curve is not None and len(loudness_curve):
            lo = int(len(loudness_curve) * start / duration)
            hi = max(lo + 1, int(np.ceil(len(loudness_curve) * end / duration)))
            loud = float(np.mean(loudness_curve[lo:hi]))
        key, mode = _estimate_key(
            chroma_sync[:, s[0]:s[1]].mean(axis=1).astype(np.float32))
        out.append({
            "start": round(start, 2), "end": round(end, 2),
            "label": relabel[lab],
            "tempo_bpm": round(tempo, 1),
            "loudness_db": round(loud, 1) if loud is not None else None,
            "key": int(key), "mode": mode,
        })
    return out


def _compute_sections(chroma: np.ndarray, mfcc: np.ndarray,
                      beat_frames: np.ndarray, sr: int, hop: int,
                      duration: float,
                      loudness_curve: Optional[np.ndarray]) -> list[dict]:
    """Beat-sync the matrices, label section types, assemble section dicts.

    Sparse-beat fallback: tracks where beat tracking finds little (ambient,
    pure tones, synthetic fixtures) sync on fixed ~0.5 s windows instead, so
    segmentation still works on structure that has no drums.
    """
    n_frames = chroma.shape[1]
    slices = np.asarray(beat_frames, dtype=int)
    slices = slices[(slices > 0) & (slices < n_frames)]
    # The beat grid must actually COVER the track to be a segmentation grid —
    # count alone lies (pure tones/ambient yield a few bunched pseudo-beats,
    # squeezing whole sections between two sync points). Any gap over ~4 s →
    # fall back to fixed ~0.5 s windows.
    slice_times = librosa.frames_to_time(slices, sr=sr, hop_length=hop)
    gaps = np.diff(np.concatenate([[0.0], slice_times, [duration]])) if len(slices) else [duration]
    if len(slices) < _SECTION_MIN_FRAMES or float(np.max(gaps)) > 4.0:
        step = max(1, int(0.5 * sr / hop))
        slices = np.arange(step, n_frames, step)
    if len(slices) == 0:
        return [{"start": 0.0, "end": round(duration, 2), "label": 0,
                 "tempo_bpm": 0.0, "loudness_db": None, "key": -1, "mode": ""}]

    csync = librosa.util.sync(chroma, slices, aggregate=np.median)
    msync = librosa.util.sync(mfcc, slices, aggregate=np.mean)
    msync = (msync - msync.mean(axis=1, keepdims=True)) / (
        msync.std(axis=1, keepdims=True) + 1e-9)

    # Recurrence sees harmony AND timbre (z-balanced stack): chroma alone made
    # harmonically-static songs read as one section — Knights of Cydonia riffs
    # around E throughout, but its parts differ in TIMBRE (harmonica → gallop
    # → vocals). Caught by spot-checking real songs, not synthetic fixtures.
    csync_z = (csync - csync.mean(axis=1, keepdims=True)) / (
        csync.std(axis=1, keepdims=True) + 1e-9)
    rec_feats = np.vstack([csync_z, msync])

    labels = _section_labels(rec_feats, msync)
    frame_times = np.concatenate([[0.0], librosa.frames_to_time(slices, sr=sr, hop_length=hop)])
    beat_times = librosa.frames_to_time(np.asarray(beat_frames, dtype=int), sr=sr, hop_length=hop)
    return _assemble_sections(labels, frame_times, csync, beat_times,
                              duration, loudness_curve)


def sections_from_signal(signal: AudioSignal, config: Optional[DSPConfig] = None) -> list[dict]:
    """Sections straight from a signal — the backfill path for existing local
    audio (chroma + MFCC + beats + RMS only; no HPSS/spectrogram). Identical
    core to the in-extractor path, so backfilled sections match fresh ones."""
    if config is None:
        config = DSPConfig()
    y, sr = signal.waveform, signal.sr
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=config.hop_length)
    _tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=config.hop_length, onset_envelope=onset_env)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=config.hop_length, n_chroma=12)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=config.n_mfcc,
                                n_fft=config.n_fft, hop_length=config.hop_length,
                                n_mels=config.n_mels)
    rms = librosa.feature.rms(y=y, frame_length=config.n_fft, hop_length=config.hop_length)[0]
    return _compute_sections(chroma, mfcc, beat_frames, sr, config.hop_length,
                             signal.duration_sec, _downsample_loudness_db(rms))


def _downsample_loudness_db(rms: np.ndarray, n_points: int = LOUDNESS_CURVE_POINTS) -> np.ndarray:
    """Downsample a per-frame RMS envelope to `n_points` of dBFS.

    Averages RMS *in the linear domain* per time-bin, then converts to dBFS
    (energy averaging is the correct order). Fewer frames than n_points → full
    resolution (one frame per bin). dBFS references full-scale 1.0, matching the
    perceptual `loudness_db` scalar (whose value is this curve's overall mean).
    """
    if rms.size == 0:
        return np.zeros(0, dtype=np.float32)
    n = int(min(n_points, rms.size))
    binned = np.array([chunk.mean() for chunk in np.array_split(rms, n)])
    db = 20.0 * np.log10(np.maximum(binned, _LOUDNESS_FLOOR))
    return db.astype(np.float32)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA STRUCTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class TrackFeatures:
    """
    Complete feature extraction result for a single audio track.

    Contains both the summary vector (for tabular ML / vector search)
    and the full 2D matrices (for deep learning / spectrogram visualization).
    """
    # ── Identification ──
    file_name: str
    file_path: str
    duration_sec: float

    # ── Rhythm Features ──
    tempo_bpm: float = 0.0
    onset_strength_mean: float = 0.0
    onset_strength_std: float = 0.0
    beat_count: int = 0
    beats_per_sec: float = 0.0
    # Estimated beats-per-bar (meter numerator), 0 = unknown. A coarse estimate
    # from beat-accent periodicity, not a scalar off a single transform — so it
    # rides as a promoted cache column (F-v2), never in the frozen vector/dict.
    time_signature: int = 0
    # Detected beat times (seconds) — the beat grid (F-v2c). Display data, like
    # the loudness curve: a cache column, never in the vector/82-col dict.
    beat_times: Optional[np.ndarray] = None
    # Detected structural sections (F-v3): [{start, end, label, loudness_db,
    # tempo_bpm, key, mode}, ...] — same label = the same-sounding section
    # (repeats). HONEST boundaries from self-similarity; we never claim
    # "chorus"/"verse" (semantic labels aren't reliably inferable). Display
    # data: a cache column, never in the frozen vector / 82-col dict.
    sections: Optional[list] = None

    # ── Energy Features ──
    rms_mean: float = 0.0
    rms_std: float = 0.0
    zcr_mean: float = 0.0              # zero crossing rate
    zcr_std: float = 0.0
    # Downsampled per-frame loudness (dBFS) — the within-track loudness curve
    # (rebuilds Spotify's deprecated get-audio-analysis loudness series). Display
    # data only: NOT part of the frozen 77-dim vector or the 82-col summary dict.
    loudness_curve: Optional[np.ndarray] = None   # shape: (<=LOUDNESS_CURVE_POINTS,)

    # ── Timbre Features (MFCC summary) ──
    mfcc_means: Optional[np.ndarray] = None   # shape: (n_mfcc,)
    mfcc_stds: Optional[np.ndarray] = None

    # ── Spectral Shape ──
    spectral_centroid_mean: float = 0.0
    spectral_centroid_std: float = 0.0
    spectral_rolloff_mean: float = 0.0
    spectral_rolloff_std: float = 0.0
    spectral_bandwidth_mean: float = 0.0
    spectral_bandwidth_std: float = 0.0
    spectral_flatness_mean: float = 0.0
    spectral_contrast_means: Optional[np.ndarray] = None  # shape: (7,)
    spectral_contrast_stds: Optional[np.ndarray] = None

    # ── Tonal Features ──
    chroma_means: Optional[np.ndarray] = None   # shape: (12,)
    chroma_stds: Optional[np.ndarray] = None
    estimated_key: int = -1       # pitch class 0-11 (C=0, C#=1, ... B=11)
    estimated_mode: str = ""      # "major" or "minor"

    # ── Acousticness Proxy ──
    harmonic_ratio: float = 0.0   # energy(harmonic) / energy(harmonic + percussive)

    # ── Full 2D Matrices (for deep learning / visualization) ──
    mel_spectrogram_db: Optional[np.ndarray] = None   # shape: (n_mels, T)
    mfcc_matrix: Optional[np.ndarray] = None          # shape: (n_mfcc, T)
    chroma_matrix: Optional[np.ndarray] = None         # shape: (12, T)

    def to_summary_vector(self) -> np.ndarray:
        """
        Flatten all scalar + array summary stats into a single 1D vector.
        This is the representation used for vector similarity search.

        Vector layout:
            [tempo, onset_mean, onset_std, beat_rate,
             rms_mean, rms_std, zcr_mean, zcr_std,
             mfcc_means(13), mfcc_stds(13),
             centroid_mean, centroid_std, rolloff_mean, rolloff_std,
             contrast_means(7), contrast_stds(7),
             chroma_means(12), chroma_stds(12),
             harmonic_ratio]
        Total: 4 + 4 + 26 + 4 + 14 + 24 + 1 = 77 dimensions
        """
        parts = [
            # Rhythm (4)
            np.array([self.tempo_bpm, self.onset_strength_mean,
                      self.onset_strength_std, self.beats_per_sec]),
            # Energy (4)
            np.array([self.rms_mean, self.rms_std, self.zcr_mean, self.zcr_std]),
            # Timbre — MFCCs (26)
            self.mfcc_means if self.mfcc_means is not None else np.zeros(13),
            self.mfcc_stds if self.mfcc_stds is not None else np.zeros(13),
            # Spectral shape (4)
            np.array([self.spectral_centroid_mean, self.spectral_centroid_std,
                      self.spectral_rolloff_mean, self.spectral_rolloff_std]),
            # Spectral contrast (14)
            self.spectral_contrast_means if self.spectral_contrast_means is not None else np.zeros(7),
            self.spectral_contrast_stds if self.spectral_contrast_stds is not None else np.zeros(7),
            # Chroma (24)
            self.chroma_means if self.chroma_means is not None else np.zeros(12),
            self.chroma_stds if self.chroma_stds is not None else np.zeros(12),
            # Acousticness proxy (1)
            np.array([self.harmonic_ratio]),
        ]
        return np.concatenate(parts).astype(np.float32)

    def to_summary_dict(self) -> dict:
        """Flatten into a dict suitable for a single DataFrame row."""
        d = {
            "file_name": self.file_name,
            "file_path": self.file_path,
            "duration_sec": self.duration_sec,
            "tempo_bpm": self.tempo_bpm,
            "onset_strength_mean": self.onset_strength_mean,
            "onset_strength_std": self.onset_strength_std,
            "beat_count": self.beat_count,
            "beats_per_sec": self.beats_per_sec,
            "rms_mean": self.rms_mean,
            "rms_std": self.rms_std,
            "zcr_mean": self.zcr_mean,
            "zcr_std": self.zcr_std,
            "spectral_centroid_mean": self.spectral_centroid_mean,
            "spectral_centroid_std": self.spectral_centroid_std,
            "spectral_rolloff_mean": self.spectral_rolloff_mean,
            "spectral_rolloff_std": self.spectral_rolloff_std,
            "spectral_bandwidth_mean": self.spectral_bandwidth_mean,
            "spectral_bandwidth_std": self.spectral_bandwidth_std,
            "spectral_flatness_mean": self.spectral_flatness_mean,
            "harmonic_ratio": self.harmonic_ratio,
            "estimated_key": self.estimated_key,
            "estimated_mode": self.estimated_mode,
        }
        # Expand array features into named columns
        if self.mfcc_means is not None:
            for i, v in enumerate(self.mfcc_means):
                d[f"mfcc_mean_{i}"] = float(v)
            for i, v in enumerate(self.mfcc_stds):
                d[f"mfcc_std_{i}"] = float(v)
        if self.chroma_means is not None:
            pitch_classes = ["C", "C#", "D", "D#", "E", "F",
                             "F#", "G", "G#", "A", "A#", "B"]
            for i, v in enumerate(self.chroma_means):
                d[f"chroma_mean_{pitch_classes[i]}"] = float(v)
            if self.chroma_stds is not None:
                for i, v in enumerate(self.chroma_stds):
                    d[f"chroma_std_{pitch_classes[i]}"] = float(v)
        if self.spectral_contrast_means is not None:
            for i, v in enumerate(self.spectral_contrast_means):
                d[f"spectral_contrast_mean_{i}"] = float(v)
            if self.spectral_contrast_stds is not None:
                for i, v in enumerate(self.spectral_contrast_stds):
                    d[f"spectral_contrast_std_{i}"] = float(v)
        return d

    def loudness_curve_points(self) -> Optional[list[float]]:
        """The loudness curve as a JSON-safe list of dBFS values (or None).

        Travels alongside the summary dict, not inside it — the curve is a
        variable-length time series for the deep-dive chart, not a scalar
        feature, so it never enters the vector or the warehouse feature columns.
        """
        if self.loudness_curve is None:
            return None
        return [round(float(v), 2) for v in self.loudness_curve]

    def beat_times_list(self) -> Optional[list[float]]:
        """Detected beat times (seconds) as a JSON-safe list — the beat grid
        (F-v2c). Travels alongside the summary dict, never inside it."""
        if self.beat_times is None:
            return None
        return [round(float(t), 2) for t in self.beat_times]

    def sections_list(self) -> Optional[list[dict]]:
        """Detected sections (F-v3) — already JSON-safe dicts, or None."""
        return self.sections


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN EXTRACTION PIPELINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_features(
    signal: AudioSignal,
    config: Optional[DSPConfig] = None,
) -> TrackFeatures:
    """
    Run the full DSP feature extraction pipeline on an AudioSignal.

    This is the primary entry point. It computes all feature groups
    (or a subset, based on config.feature_groups) and returns a
    TrackFeatures dataclass with both summary stats and full matrices.

    Args:
        signal: An AudioSignal from audio_loader.load_audio().
        config: Optional DSPConfig override.

    Returns:
        TrackFeatures with all computed features populated.
    """
    if config is None:
        config = DSPConfig()

    y = signal.waveform
    sr = signal.sr

    features = TrackFeatures(
        file_name=signal.file_name,
        file_path=signal.file_path,
        duration_sec=signal.duration_sec,
    )

    # ── Rhythm ──
    if config.should_extract(FeatureGroup.RHYTHM):
        _extract_rhythm(y, sr, config, features)

    # ── Energy ──
    if config.should_extract(FeatureGroup.ENERGY):
        _extract_energy(y, sr, config, features)

    # ── Timbre ──
    if config.should_extract(FeatureGroup.TIMBRE):
        _extract_timbre(y, sr, config, features)

    # ── Tonal ──
    if config.should_extract(FeatureGroup.TONAL):
        _extract_tonal(y, sr, config, features)

    # ── Spectral (mel spectrogram) ──
    if config.should_extract(FeatureGroup.SPECTRAL):
        _extract_spectral(y, sr, config, features)

    # ── Acousticness proxy (HPSS) ──
    # Always computed when either ENERGY or ALL is requested, as it
    # provides the harmonic_ratio which is our acousticness replacement.
    if config.should_extract(FeatureGroup.ENERGY):
        _extract_harmonic_ratio(y, sr, features)

    # ── Structural sections (F-v3) ──
    # Needs the rhythm/tonal/timbre/energy products; a partial config or a
    # detection failure → no sections, never an error (display data).
    if (features.chroma_matrix is not None and features.mfcc_matrix is not None
            and features.beat_times is not None and features.loudness_curve is not None):
        try:
            beat_frames = librosa.time_to_frames(
                features.beat_times, sr=sr, hop_length=config.hop_length)
            features.sections = _compute_sections(
                features.chroma_matrix, features.mfcc_matrix, beat_frames, sr,
                config.hop_length, features.duration_sec, features.loudness_curve)
        except Exception:  # noqa: BLE001 — sections are display data, never fatal
            logging.getLogger(__name__).warning(
                "section detection failed for %s", signal.file_name, exc_info=True)

    return features


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEATURE GROUP EXTRACTORS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _extract_rhythm(
    y: np.ndarray, sr: int, config: DSPConfig, features: TrackFeatures
) -> None:
    """
    Extract tempo, beat positions, and onset strength.

    Why librosa.beat.beat_track?
    It uses onset strength envelope + dynamic programming to find the
    tempo that best explains the detected onsets. More robust than
    simple autocorrelation for music with syncopation or tempo changes.
    """
    # onset_envelope: 1D array of onset strengths per frame
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=config.hop_length
    )
    features.onset_strength_mean = float(np.mean(onset_env))
    features.onset_strength_std = float(np.std(onset_env))

    # beat_track returns (tempo, beat_frame_indices)
    tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=config.hop_length, onset_envelope=onset_env
    )
    # librosa >= 0.10 returns tempo as an array; take the scalar
    features.tempo_bpm = float(np.atleast_1d(tempo)[0])
    features.beat_count = len(beat_frames)
    features.beats_per_sec = (
        features.beat_count / features.duration_sec
        if features.duration_sec > 0 else 0.0
    )
    features.time_signature = _estimate_time_signature(onset_env, beat_frames)
    features.beat_times = librosa.frames_to_time(
        beat_frames, sr=sr, hop_length=config.hop_length)


def _extract_energy(
    y: np.ndarray, sr: int, config: DSPConfig, features: TrackFeatures
) -> None:
    """
    Extract RMS energy and zero crossing rate.

    RMS (Root Mean Square) energy: measures perceived loudness per frame.
    This replaces Spotify's "energy" feature — a high RMS mean indicates
    a consistently loud, energetic track.

    ZCR (Zero Crossing Rate): counts how often the signal crosses zero
    per frame. High ZCR → noisy/percussive signal (proxy for speechiness
    or noise content). Low ZCR → tonal/harmonic signal.
    """
    rms = librosa.feature.rms(y=y, frame_length=config.n_fft, hop_length=config.hop_length)[0]
    features.rms_mean = float(np.mean(rms))
    features.rms_std = float(np.std(rms))
    # The loudness curve rides along from the RMS envelope we already computed —
    # downsampled to a fixed point count so the chart width is song-agnostic.
    features.loudness_curve = _downsample_loudness_db(rms)

    zcr = librosa.feature.zero_crossing_rate(y=y, frame_length=config.n_fft, hop_length=config.hop_length)[0]
    features.zcr_mean = float(np.mean(zcr))
    features.zcr_std = float(np.std(zcr))


def _extract_timbre(
    y: np.ndarray, sr: int, config: DSPConfig, features: TrackFeatures
) -> None:
    """
    Extract MFCCs, spectral centroid, spectral rolloff, and spectral contrast.

    MFCCs (Mel-Frequency Cepstral Coefficients): capture the spectral envelope
    — the "shape" of the frequency spectrum that distinguishes a piano from a
    guitar even when playing the same note. 13 coefficients is the classic choice
    from speech/music processing. The 0th coefficient represents overall energy,
    coefficients 1-12 capture progressively finer spectral detail.

    Spectral centroid: the "center of mass" of the spectrum. Bright instruments
    (cymbals, hi-hats) have high centroid. Dark instruments (bass, cello) have low.

    Spectral rolloff: the frequency below which 85% of spectral energy is
    concentrated. Another brightness measure, but more robust to outlier harmonics.

    Spectral contrast: measures the difference between peaks and valleys in
    each sub-band of the spectrum. High contrast → clear harmonic content.
    Low contrast → noisy/percussive content.
    """
    # -- MFCCs --
    mfcc = librosa.feature.mfcc(
        y=y, sr=sr, n_mfcc=config.n_mfcc,
        n_fft=config.n_fft, hop_length=config.hop_length, n_mels=config.n_mels,
    )
    features.mfcc_matrix = mfcc
    features.mfcc_means = np.mean(mfcc, axis=1).astype(np.float32)
    features.mfcc_stds = np.std(mfcc, axis=1).astype(np.float32)

    # -- Spectral centroid --
    centroid = librosa.feature.spectral_centroid(
        y=y, sr=sr, n_fft=config.n_fft, hop_length=config.hop_length
    )[0]
    features.spectral_centroid_mean = float(np.mean(centroid))
    features.spectral_centroid_std = float(np.std(centroid))

    # -- Spectral rolloff --
    rolloff = librosa.feature.spectral_rolloff(
        y=y, sr=sr, n_fft=config.n_fft, hop_length=config.hop_length
    )[0]
    features.spectral_rolloff_mean = float(np.mean(rolloff))
    features.spectral_rolloff_std = float(np.std(rolloff))

    # -- Spectral bandwidth --
    # The weighted spread of the spectrum around its centroid: narrow
    # bandwidth → pure/tonal sound, wide bandwidth → noisy/dense mix.
    bandwidth = librosa.feature.spectral_bandwidth(
        y=y, sr=sr, n_fft=config.n_fft, hop_length=config.hop_length
    )[0]
    features.spectral_bandwidth_mean = float(np.mean(bandwidth))
    features.spectral_bandwidth_std = float(np.std(bandwidth))

    # -- Spectral flatness --
    # Geometric/arithmetic mean ratio of the spectrum: 1.0 → white noise,
    # near 0 → strongly tonal. Complements harmonic_ratio.
    flatness = librosa.feature.spectral_flatness(
        y=y, n_fft=config.n_fft, hop_length=config.hop_length
    )[0]
    features.spectral_flatness_mean = float(np.mean(flatness))

    # -- Spectral contrast (7 bands by default) --
    contrast = librosa.feature.spectral_contrast(
        y=y, sr=sr, n_fft=config.n_fft, hop_length=config.hop_length
    )
    features.spectral_contrast_means = np.mean(contrast, axis=1).astype(np.float32)
    features.spectral_contrast_stds = np.std(contrast, axis=1).astype(np.float32)


def _extract_tonal(
    y: np.ndarray, sr: int, config: DSPConfig, features: TrackFeatures
) -> None:
    """
    Extract chroma features and estimate key/mode.

    Chroma (using CQT — Constant-Q Transform): projects audio onto the 12
    pitch classes (C, C#, D, ..., B). This is the Harmonic Pitch Class Profile
    (HPCP) referenced in the DSP architect prompt. CQT-based chroma is preferred
    over STFT-based chroma for polyphonic music because CQT has logarithmic
    frequency resolution that matches the musical scale.

    Key estimation: the pitch class with the highest mean chroma energy is the
    estimated tonic. Mode (major/minor) is estimated by comparing the chroma
    profile against major and minor templates (Krumhansl-Kessler profiles).
    """
    chroma = librosa.feature.chroma_cqt(
        y=y, sr=sr, hop_length=config.hop_length, n_chroma=12
    )
    features.chroma_matrix = chroma
    features.chroma_means = np.mean(chroma, axis=1).astype(np.float32)
    features.chroma_stds = np.std(chroma, axis=1).astype(np.float32)

    # Key estimation via Krumhansl-Kessler profiles
    features.estimated_key, features.estimated_mode = _estimate_key(features.chroma_means)


def _extract_spectral(
    y: np.ndarray, sr: int, config: DSPConfig, features: TrackFeatures
) -> None:
    """
    Compute the log-scaled Mel spectrogram.

    This 2D matrix is the primary input for deep learning models (CNNs, PANNs).
    We log-scale (dB) the power spectrogram because:
    1. Human hearing is logarithmic in perceived loudness (Weber-Fechner law).
    2. Raw power values span many orders of magnitude, which creates vanishing
       gradient problems in neural networks. dB scaling compresses this range.

    Output shape: (n_mels, T) where T = ceil(n_samples / hop_length).
    """
    mel_spec = librosa.feature.melspectrogram(
        y=y, sr=sr,
        n_fft=config.n_fft, hop_length=config.hop_length, n_mels=config.n_mels,
    )
    # Convert to log scale (dB). ref=np.max normalizes relative to peak.
    features.mel_spectrogram_db = librosa.power_to_db(
        mel_spec, ref=np.max, top_db=config.top_db
    )


def _extract_harmonic_ratio(
    y: np.ndarray, sr: int, features: TrackFeatures
) -> None:
    """
    Compute harmonic-to-total energy ratio via HPSS.

    HPSS (Harmonic-Percussive Source Separation) decomposes audio into:
    - Harmonic component: sustained tones (vocals, strings, synth pads)
    - Percussive component: transients (drums, clicks, consonants)

    harmonic_ratio = energy(harmonic) / energy(total)
    - Close to 1.0 → highly acoustic/harmonic (replaces Spotify "acousticness")
    - Close to 0.0 → highly percussive/noisy

    This is computed on the waveform domain (not spectrogram) for accuracy.
    """
    y_harmonic, y_percussive = librosa.effects.hpss(y)

    energy_total = float(np.sum(y ** 2))
    energy_harmonic = float(np.sum(y_harmonic ** 2))

    features.harmonic_ratio = (
        energy_harmonic / energy_total if energy_total > 1e-10 else 0.0
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  KEY ESTIMATION HELPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Krumhansl-Kessler key profiles (normalized weights for each pitch class).
# These are empirically derived from listener probe-tone experiments and
# represent how "stable" each pitch class sounds in a given key context.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F",
                  "F#", "G", "G#", "A", "A#", "B"]


def _estimate_key(chroma_means: np.ndarray) -> tuple[int, str]:
    """
    Estimate musical key from mean chroma vector using correlation with
    Krumhansl-Kessler profiles.

    For each of the 12 possible tonics, we circularly shift the major and
    minor profiles and compute Pearson correlation with the observed chroma.
    The tonic + mode with the highest correlation wins.

    Returns:
        (key_index, mode_string): e.g., (0, "major") means C major.
    """
    best_corr = -np.inf
    best_key = 0
    best_mode = "major"

    for shift in range(12):
        # Rotate profile to test each possible tonic
        major_shifted = np.roll(_MAJOR_PROFILE, shift)
        minor_shifted = np.roll(_MINOR_PROFILE, shift)

        corr_major = np.corrcoef(chroma_means, major_shifted)[0, 1]
        corr_minor = np.corrcoef(chroma_means, minor_shifted)[0, 1]

        if corr_major > best_corr:
            best_corr = corr_major
            best_key = shift
            best_mode = "major"
        if corr_minor > best_corr:
            best_corr = corr_minor
            best_key = shift
            best_mode = "minor"

    return best_key, best_mode
