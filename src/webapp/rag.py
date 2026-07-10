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

import json
import logging
import re
from typing import Any, Optional

from . import config

logger = logging.getLogger(__name__)

_JSON_BLOB = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(text: str) -> Optional[dict]:
    """Parse a model's JSON reply: strip code fences, grab the outermost object.

    Returns None on failure — and LOGS it (a silently-swallowed parse error
    once shipped a whole empty column; KB structured-output card). The caller
    falls back deterministically, never fakes success.
    """
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip("` \n")
    m = _JSON_BLOB.search(cleaned)
    if not m:
        logger.warning("LLM reply had no JSON object (len=%d)", len(text))
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("LLM JSON failed to parse: %s", exc)
        return None
    return obj if isinstance(obj, dict) else None

# Interpretable features we surface + gloss (must exist in column_descriptions).
_GLOSSARY_FEATURES = ["tempo_bpm", "rms_mean", "spectral_centroid_mean"]

_SYSTEM = (
    "You are a warm, precise music-taste analyst for Vercillo Analytics. Answer "
    "the visitor's question USING ONLY the DATA provided about their own Spotify "
    "listening and its local acoustic analysis. Cite their real tracks, artists, "
    "genres, and numbers. NEVER invent tracks, artists, or statistics that are not "
    "in the DATA. If the DATA cannot answer the question, say what you can see "
    "instead.\n"
    "Reply as a single JSON object with EXACTLY these fields, in this order:\n"
    '  "thoughts": your brief reasoning about what the DATA supports (1-2 sentences),\n'
    '  "answer": the reply shown to the visitor — 2-4 sentences, second person '
    '("you"), no preamble, plain prose, no markdown,\n'
    '  "cited": a JSON array of the exact track/artist/cluster names from the DATA '
    "that your answer mentions.\n"
    "Output only the JSON object."
)

_MAX_TOKENS = 1024  # a taste answer is deliberately short — well under stream/timeout limits


def _grounding_text(taste: dict[str, Any], glossary: dict[str, str]) -> str:
    """Render the visitor's retrieved facts as the grounding block for the prompt."""
    lines: list[str] = []
    cov = taste.get("coverage") or {}
    if cov:
        lines.append(
            f"Analyzed songs: {cov.get('analyzed', 0)} of {cov.get('total', 0)} of your "
            f"top tracks have local audio features ({cov.get('analyzing', 0)} still analyzing).")
    prof = taste.get("profile") or {}
    if prof.get("message"):
        lines.append(prof["message"])
    for h in prof.get("highlights", []):
        lines.append(f"  - {h}")
    arch = taste.get("archetype")
    if arch:
        lines.append(f"Taste archetype (derived): {arch['name']} — "
                     + "; ".join(arch.get("evidence", [])))
    clusters = taste.get("clusters") or {}
    for window, segs in (clusters.get("windows") or {}).items():
        seg_s = ", ".join(f"{s['share']}% “{s['label']}”" for s in segs[:3])
        lines.append(f"Sound buckets ({window}): {seg_s}.")
    if clusters.get("movement"):
        lines.append(f"Cluster movement: {clusters['movement']}")
    sig = taste.get("signature") or []
    if sig:
        lines.append("Acoustic signature vs the corpus: "
                     + "; ".join(f"{s['feature']} {s['word']} ({s['z']:+.1f}σ)"
                                 for s in sig))
    drift = taste.get("drift")
    if drift:
        lines.append(
            f"Taste drift (recent vs all-time): {drift['label']} "
            f"(RMS sigma-shift {drift['score']}, {drift.get('n_short', '?')} vs "
            f"{drift.get('n_long', '?')} overlapping tracks).")
    pop = taste.get("popularity")
    if pop:
        lines.append(f"Popularity context (Spotify metadata, not acoustic): {pop}")
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
                parsed = self._llm_answer(question, grounding, key)
                if parsed and parsed.get("answer"):
                    return {"answer": str(parsed["answer"]).strip(), "source": "llm",
                            "model": self.model,
                            "cited": [str(c) for c in parsed.get("cited") or []]}
            except Exception as exc:  # noqa: BLE001 — an LLM error must never fail the request
                logger.warning("RAG LLM answer failed (%s) — deterministic fallback", exc)
        return {"answer": self._fallback(taste), "source": "fallback", "model": None}

    # ── Epic D: the taste-profile classification ───────────────────────────
    def classify(self, taste: dict[str, Any]) -> dict[str, Any]:
        """A grounded taste profile for the derived archetype.

        Returns {name, narrative, source}. The archetype NAME is always the
        deterministic one (the model may not rebrand the listener); the LLM
        only writes the narrative — and without a key, the narrative is
        assembled from the same evidence (D-5).
        """
        arch = taste.get("archetype")
        if not arch:
            return {"name": None, "narrative": "", "source": "none"}
        glossary = self.fs.feature_glossary(_GLOSSARY_FEATURES) if self.fs else {}
        grounding = _grounding_text(taste, glossary)
        key = config.anthropic_key()
        if key:
            try:
                system = (
                    "You write a short second-person music-taste profile for the "
                    f"archetype \"{arch['name']}\". Use ONLY the DATA: cite the real "
                    "cluster names, artists, and numbers it contains; invent nothing.\n"
                    "Reply as a single JSON object with EXACTLY these fields, in this order:\n"
                    '  "thoughts": brief reasoning about what the DATA supports,\n'
                    '  "narrative": the profile shown to the visitor — 3-5 sentences, warm '
                    "but specific, plain prose, no markdown, no preamble, do not restate "
                    "the archetype name in the first sentence,\n"
                    '  "cited": a JSON array of the exact cluster/artist names your '
                    "narrative mentions.\n"
                    "Output only the JSON object.")
                import anthropic
                client = anthropic.Anthropic(api_key=key)
                resp = client.messages.create(
                    model=self.model, max_tokens=_MAX_TOKENS, system=system,
                    messages=[{"role": "user", "content": f"DATA:\n{grounding}"}])
                if resp.stop_reason != "refusal":
                    text = next((b.text for b in resp.content if b.type == "text"), "")
                    parsed = _parse_llm_json(text)
                    if parsed and parsed.get("narrative"):
                        return {"name": arch["name"],
                                "narrative": str(parsed["narrative"]).strip(),
                                "cited": [str(c) for c in parsed.get("cited") or []],
                                "source": "llm", "model": self.model}
            except Exception as exc:  # noqa: BLE001 — never fail the page
                logger.warning("classify LLM failed (%s) — deterministic narrative", exc)
        return {"name": arch["name"], "narrative": self._archetype_narrative(taste),
                "source": "fallback", "model": None}

    def _archetype_narrative(self, taste: dict[str, Any]) -> str:
        """Deterministic profile text from the archetype evidence (D-5)."""
        arch = taste["archetype"]
        artists = taste.get("artists") or []
        parts = [f"Your home sound is “{arch['home']}” — "
                 + arch["evidence"][0].split("— ")[-1] + "."]
        if len(arch["evidence"]) > 1:
            parts.append(arch["evidence"][1][0].upper() + arch["evidence"][1][1:] + ".")
        if arch.get("motion"):
            parts.append(f"Between your recent and all-time listening you read as "
                         f"{arch['motion'].lower()}.")
        if artists:
            parts.append(f"{artists[0]['name']} anchors it all.")
        return " ".join(parts)

    def _llm_answer(self, question: str, grounding: str, key: str) -> Optional[dict]:
        """LLM call under the A2 JSON contract → {thoughts, answer, cited} or None."""
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
            return None
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _parse_llm_json(text)

    def _fallback(self, taste: dict[str, Any]) -> str:
        """Deterministic, visitor-facing answer from the retrieved facts (D-5)."""
        prof = taste.get("profile") or {}
        drift = taste.get("drift")
        artists = taste.get("artists") or []
        parts: list[str] = []
        if prof.get("message"):
            parts.append(prof["message"])
        if artists:
            parts.append(f"Your most-played artist is {artists[0]['name']}.")
        if drift and drift.get("label"):
            parts.append("Recent vs all-time, your taste shows "
                         f"{drift['label'].split('(')[0].strip().lower()}.")
        if not parts:
            return ("Your songs are still being analyzed — check back shortly for your "
                    "acoustic profile, or see your top tracks and artists on the dashboard.")
        return " ".join(parts)
