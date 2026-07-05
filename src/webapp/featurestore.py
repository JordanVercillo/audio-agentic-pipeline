"""
featurestore.py — the bridge key as a shared feature store (SPEC P8).

A visitor's top-track `spotify_track_id`s are joined against OUR local DSP
corpus (the gold `fact_listening_features`). Overlapping tracks get real
acoustic treatment; the rest get metadata only. Visitors NEVER trigger audio
acquisition (non-goal preserved) — this is a read of the derived feature store.

The corpus is one listener's taste (~118 tracks), so a stranger's overlap may
be small or zero. `profile()` handles that honestly: zero overlap returns a
graceful, non-empty result rather than pretending.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

# Interpretable features for the human-readable insight: (column, label, unit, "up" verb).
_INSIGHT_FEATURES = [
    ("tempo_bpm", "tempo", "bpm", "faster"),
    ("rms_mean", "energy", "", "louder"),
    ("spectral_centroid_mean", "brightness", "", "brighter"),
]
_SIMILAR_BAND = 0.08  # within ±8% of the corpus mean ⇒ "on par"


class FeatureStore:
    """Loads the gold acoustic corpus once; joins visitor tracks against it."""

    def __init__(self, modeled_dir: Union[str, Path]) -> None:
        self.modeled_dir = Path(modeled_dir)
        fact_path = self.modeled_dir / "fact_listening_features.parquet"
        if not fact_path.exists():
            raise FileNotFoundError(
                f"No gold features at {fact_path} — run the pipeline first.")

        fact = pd.read_parquet(fact_path)
        # Grain is (track, time_range); collapse to one row per distinct track.
        self._corpus = fact.drop_duplicates(subset="spotify_track_id").set_index(
            "spotify_track_id")
        self.corpus_ids: set[str] = set(self._corpus.index)

        self._feature_cols = [c for c, *_ in _INSIGHT_FEATURES if c in self._corpus.columns]
        self._corpus_means = {c: float(self._corpus[c].mean()) for c in self._feature_cols}

        # Optional genre/cluster labels for a nameable insight.
        self._genre: dict[str, str] = {}
        ca_path = self.modeled_dir / "cluster_assignments.parquet"
        if ca_path.exists():
            ca = pd.read_parquet(ca_path)
            if {"spotify_track_id", "genre_bucket"}.issubset(ca.columns):
                self._genre = dict(zip(ca["spotify_track_id"], ca["genre_bucket"], strict=False))

    # ── the join ──────────────────────────────────────────────────────────
    def profile(self, track_ids: list[str]) -> dict[str, Any]:
        """
        Join `track_ids` against the corpus and describe the overlap.

        Returns a dict the dashboard renders directly:
            corpus_size, overlap_count, overlap_ids, matched[], highlights[],
            dominant_genre, message.
        """
        seen: list[str] = []
        for tid in track_ids:  # dedup, preserve visitor order
            if tid not in seen:
                seen.append(tid)
        overlap_ids = [t for t in seen if t in self.corpus_ids]

        base: dict[str, Any] = {
            "corpus_size": len(self.corpus_ids),
            "overlap_count": len(overlap_ids),
            "overlap_ids": overlap_ids,
            "matched": [],
            "highlights": [],
            "dominant_genre": None,
        }

        if not overlap_ids:
            base["message"] = (
                f"None of your top tracks are in our {len(self.corpus_ids)}-track "
                "acoustic corpus yet — so this is the metadata view. The feature "
                "store lights up on shared tracks: their real DSP features (tempo, "
                "energy, brightness, 77-dim vectors) join instantly on the bridge key."
            )
            return base

        subset = self._corpus.loc[overlap_ids]

        highlights: list[str] = []
        for col, label, unit, up_verb in _INSIGHT_FEATURES:
            if col not in self._feature_cols:
                continue
            sub_mean = float(subset[col].mean())
            corp_mean = self._corpus_means[col]
            if corp_mean == 0:
                continue
            rel = (sub_mean - corp_mean) / abs(corp_mean)
            unit_s = f" {unit}" if unit else ""
            if abs(rel) < _SIMILAR_BAND:
                highlights.append(
                    f"{label} on par with the corpus ({_fmt(sub_mean)}{unit_s})")
            else:
                verb = up_verb if rel > 0 else _down_verb(up_verb)
                highlights.append(
                    f"{abs(rel) * 100:.0f}% {verb} than the corpus "
                    f"({_fmt(sub_mean)} vs {_fmt(corp_mean)}{unit_s})")

        genres = [self._genre.get(t) for t in overlap_ids if self._genre.get(t)]
        dominant = max(set(genres), key=genres.count) if genres else None

        base["matched"] = [
            {
                "spotify_track_id": t,
                "track_name": _safe(subset.loc[t, "track_name"]),
                "artist": _safe(subset.loc[t, "primary_artist_name"]),
                "genre_bucket": self._genre.get(t),
            }
            for t in overlap_ids
        ]
        base["highlights"] = highlights
        base["dominant_genre"] = dominant
        n = len(overlap_ids)
        genre_bit = f", leaning **{dominant}**" if dominant else ""
        base["message"] = (
            f"{n} of your top tracks overlap our acoustic corpus{genre_bit}. "
            "Their real DSP features vs the corpus: " + "; ".join(highlights) + "."
            if highlights
            else f"{n} of your top tracks overlap our acoustic corpus{genre_bit}."
        )
        return base


def _fmt(v: float) -> str:
    """Adaptive precision so small-magnitude features (rms ~0.2) don't round to 0."""
    a = abs(v)
    if a >= 10:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _down_verb(up_verb: str) -> str:
    return {"faster": "slower", "louder": "quieter", "brighter": "darker"}.get(
        up_verb, "lower")


def _safe(v: Any) -> Optional[str]:
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
