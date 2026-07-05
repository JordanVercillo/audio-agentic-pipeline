"""
rag.py — grounded taste Q&A (SPEC P8 slice 2).

Answers a visitor's free-text question about their taste, GROUNDED strictly on
their own retrieved data: the acoustic overlap insight, taste drift, top
artists/genres, top tracks, and the gold `column_descriptions` feature glossary
(the same feature store P5's agent reads — shared retrieval core, D-10/D-5).

    - With ANTHROPIC_API_KEY: Claude writes the answer from the grounding block,
      instructed to cite only what's in the data and invent nothing.
    - Without a key: a deterministic template answer from the same facts (D-5).

The LLM only ever sees the visitor's retrieved rows — it does not free-associate.
A SQL-tool variant (letting the model query a per-session WarehouseAgent over the
visitor's Parquet) is the documented next extension; here the app composes the
retrieval, which is the lower-surface, higher-precision path for a public pilot.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import config

logger = logging.getLogger(__name__)

# Interpretable features we surface + gloss (must exist in column_descriptions).
_GLOSSARY_FEATURES = ["tempo_bpm", "rms_mean", "spectral_centroid_mean"]

_SYSTEM = (
    "You are a warm, precise music-taste analyst for Vercillo Analytics. Answer "
    "the visitor's question USING ONLY the DATA provided about their own Spotify "
    "listening and its local acoustic analysis. Cite their real tracks, artists, "
    "genres, and numbers. NEVER invent tracks, artists, or statistics that are not "
    "in the DATA. If the DATA cannot answer the question, say what you can see "
    "instead. 2–4 sentences, second person (\"you\"), no preamble, plain prose "
    "with no markdown formatting."
)

_MAX_TOKENS = 1024  # a taste answer is deliberately short — well under stream/timeout limits


def _grounding_text(taste: dict[str, Any], glossary: dict[str, str]) -> str:
    """Render the visitor's retrieved facts as the grounding block for the prompt."""
    lines: list[str] = []
    prof = taste.get("profile") or {}
    if prof:
        head = f"Acoustic corpus overlap: {prof.get('overlap_count', 0)} of your top tracks"
        if prof.get("dominant_genre"):
            head += f", leaning {prof['dominant_genre']}"
        lines.append(head + ".")
        for h in prof.get("highlights", []):
            lines.append(f"  - {h}")
    drift = taste.get("drift")
    if drift:
        lines.append(
            f"Taste drift (recent vs all-time): {drift['label']} "
            f"(RMS sigma-shift {drift['score']}, {drift.get('n_short', '?')} vs "
            f"{drift.get('n_long', '?')} overlapping tracks).")
    artists = taste.get("artists") or []
    if artists:
        alist = "; ".join(
            a["name"] + (f" [{a['genres']}]" if a.get("genres") else "")
            for a in artists[:10])
        lines.append(f"Top artists: {alist}.")
    for rng in taste.get("ranges", []):
        tracks = rng.get("tracks", [])
        if tracks:
            tl = "; ".join(
                f"{t['name']} — {t['artist']}" + (" [in corpus]" if t.get("in_corpus") else "")
                for t in tracks[:8])
            lines.append(f"Top tracks ({rng['label']}): {tl}.")
    if glossary:
        lines.append("Feature glossary: "
                     + " ".join(f"{k} = {v}" for k, v in glossary.items()))
    return "\n".join(lines) if lines else "(no listening data available)"


class TasteRAG:
    """Grounded taste Q&A over the visitor's own retrieved data."""

    def __init__(self, feature_store: Any = None, model: Optional[str] = None) -> None:
        self.fs = feature_store
        self.model = model or config.rag_model()

    def answer(self, question: str, taste: dict[str, Any]) -> dict[str, Any]:
        """Return {answer, source, model}. Never raises — falls back deterministically."""
        glossary = self.fs.feature_glossary(_GLOSSARY_FEATURES) if self.fs else {}
        grounding = _grounding_text(taste, glossary)
        key = config.anthropic_key()
        if key:
            try:
                text = self._llm_answer(question, grounding, key)
                if text:
                    return {"answer": text, "source": "llm", "model": self.model}
            except Exception as exc:  # noqa: BLE001 — an LLM error must never fail the request
                logger.warning("RAG LLM answer failed (%s) — deterministic fallback", exc)
        return {"answer": self._fallback(taste), "source": "fallback", "model": None}

    def _llm_answer(self, question: str, grounding: str, key: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        prompt = (
            "DATA (the visitor's own listening + local acoustic analysis):\n"
            f"{grounding}\n\nQUESTION: {question}")
        resp = client.messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            return ""
        return next((b.text for b in resp.content if b.type == "text"), "").strip()

    def _fallback(self, taste: dict[str, Any]) -> str:
        """Deterministic, visitor-facing answer from the retrieved facts (D-5)."""
        prof = taste.get("profile") or {}
        drift = taste.get("drift")
        artists = taste.get("artists") or []
        bits: list[str] = []
        if prof.get("dominant_genre"):
            bits.append(f"your acoustic overlap leans {prof['dominant_genre']}")
        if artists:
            bits.append(f"your top artist is {artists[0]['name']}")
        if drift:
            bits.append("your recent-vs-all-time taste shows "
                        f"{drift['label'].split('(')[0].strip().lower()}")
        if prof.get("highlights"):
            bits.append(prof["highlights"][0])
        if not bits:
            return ("There isn't enough overlap with our acoustic corpus to profile your "
                    "taste yet — your dashboard still shows your top tracks and artists.")
        return "Based on your listening, " + "; ".join(bits) + "."
