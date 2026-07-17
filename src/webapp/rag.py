"""
rag.py — grounded taste Q&A (SPEC P8 slice 2).

Answers a visitor's free-text question about their taste, GROUNDED strictly on
their own retrieved data: the acoustic overlap insight, taste drift, top
artists/genres, top tracks, and the gold `column_descriptions` feature glossary
(the same feature store P5's agent reads — shared retrieval core, D-10/D-5).

    - `WEBAPP_LLM_MODEL=ollama:gemma4:12b`: a LOCAL model writes it, $0, no key
      (A3) — instructed to cite only what's in the data and invent nothing.
    - Otherwise with ANTHROPIC_API_KEY: Claude does the same from the grounding.
    - With neither: a deterministic template answer from the same facts (D-5).

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
    "listening and its local acoustic analysis. NEVER invent tracks, artists, or "
    "statistics that are not in the DATA. If the DATA cannot answer the question, "
    "say what you can see instead.\n"
    "GROUND CONCRETELY: name at least one of their actual artists or tracks from "
    "the DATA, and when the DATA gives a labelled result (a drift label like "
    "\"Moderate drift\", a sound-bucket name, an archetype), reuse that label "
    "VERBATIM — copy its exact words, never paraphrase it into a synonym.\n"
    "Reply as a single JSON object with EXACTLY these fields, in this order:\n"
    '  "thoughts": your brief reasoning about what the DATA supports (1-2 sentences),\n'
    '  "answer": the reply shown to the visitor — 2-4 sentences, second person '
    '("you"), no preamble, plain prose, no markdown,\n'
    '  "cited": a JSON array of the exact track/artist/cluster names from the DATA '
    "that your answer mentions.\n"
    "Output only the JSON object."
)

_MAX_TOKENS = 1024  # a taste answer is deliberately short — well under stream/timeout limits

# A3 — the local Ollama path. gemma4:12b's 262K default context inflates the KV
# cache past a 12 GB card's free VRAM (measured 29% CPU spill); our grounding is
# ~2K tokens, so cap num_ctx to keep weights + KV fully on-GPU. format="json"
# grammar-constrains a thinking model's output to one JSON object (reasoning
# lands in the schema's `thoughts` field, not as loose prose).
_OLLAMA_NUM_CTX = 8192
# K0.5: cap generation. gemma4 is a THINKING model — uncapped at temp 0 it can
# grind a huge `thoughts` field and blow the timeout (the mechanism behind the
# two classify timeouts in the 2026-07-16 baseline). A taste answer is short.
_OLLAMA_NUM_PREDICT = 1024
_OLLAMA_TIMEOUT = 120  # seconds — covers a cold model load; warm calls are ~3-8 s

# The grounding sentinel for "this visitor has no retrieved data yet" — the
# answer() path short-circuits to the deterministic fallback on it (no LLM call).
_EMPTY_GROUNDING = "(no listening data available)"


def warm_model(model: str) -> None:
    """Preload an Ollama model so the first real /ask is fast (a cold 12B load is
    ~90 s; keep_alive holds it warm after). No-op for non-Ollama models; never
    raises — a missing server just means the first ask pays the load."""
    if not model.startswith("ollama:"):
        return
    try:
        _ollama_chat(model.split(":", 1)[1], "warm-up",
                     "Reply with an empty JSON object: {}")
        logger.info("ollama model %s warmed", model)
    except Exception as exc:  # noqa: BLE001 — warm-up is best-effort
        logger.info("ollama warm-up skipped (%s)", exc)


def _ollama_chat(model: str, system: str, prompt: str) -> Optional[str]:
    """Single-shot chat against the local Ollama server (A3, $0). Returns the
    raw content string, or None on an unexpected shape. HTTP errors propagate —
    the caller guards and falls back deterministically."""
    import requests

    resp = requests.post(
        f"{config.ollama_host()}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "format": "json", "stream": False,
            "options": {"num_ctx": _OLLAMA_NUM_CTX,
                        "num_predict": _OLLAMA_NUM_PREDICT, "temperature": 0},
            "keep_alive": "10m",  # keep it resident so back-to-back asks are warm
        },
        timeout=_OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return (resp.json().get("message") or {}).get("content")


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
        # K0.5: render motion/breadth — they were absent from the grounding, so
        # the model could not cite "read as anchored/roaming" (the C11/C12
        # context failures). Same phrasing the deterministic narrative uses.
        if arch.get("motion"):
            lines.append("Between your recent and all-time listening you read as "
                         f"{arch['motion'].lower()}.")
        if arch.get("breadth"):
            lines.append(f"Across artists you read as {arch['breadth'].lower()}.")
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
    return "\n".join(lines) if lines else _EMPTY_GROUNDING


class TasteRAG:
    """Grounded taste Q&A over the visitor's own retrieved data."""

    def __init__(self, feature_store: Any = None, model: Optional[str] = None) -> None:
        self.fs = feature_store
        self.model = model or config.rag_model()

    def _wants_llm(self) -> bool:
        """True when a real model is configured: a local Ollama model (A3, no
        key) or an Anthropic model with a key. Otherwise the deterministic path."""
        return self.model.startswith("ollama:") or bool(config.anthropic_key())

    def _chat(self, system: str, prompt: str) -> Optional[str]:
        """Provider-agnostic single-shot chat → the raw reply text, or None.
        `ollama:<model>` hits the local server ($0, A3); otherwise Anthropic
        (needs a key). May raise — callers guard and fall back."""
        if self.model.startswith("ollama:"):
            return _ollama_chat(self.model.split(":", 1)[1], system, prompt)
        key = config.anthropic_key()
        if not key:
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=self.model, max_tokens=_MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": prompt}])
        if resp.stop_reason == "refusal":
            return None
        return next((b.text for b in resp.content if b.type == "text"), "")

    def answer(self, question: str, taste: dict[str, Any]) -> dict[str, Any]:
        """Return {answer, source, model}. Never raises — falls back deterministically."""
        glossary = self.fs.feature_glossary(_GLOSSARY_FEATURES) if self.fs else {}
        grounding = _grounding_text(taste, glossary)
        # K0.5: an empty context has nothing to ground on — don't spend an LLM
        # call (and a possible cold-load timeout) to have it guess; the
        # deterministic fallback answers honestly from the retrieved facts (D-5).
        if grounding == _EMPTY_GROUNDING:
            return {"answer": self._fallback(taste), "source": "fallback", "model": None}
        if self._wants_llm():
            try:
                prompt = ("DATA (the visitor's own listening + local acoustic analysis):\n"
                          f"{grounding}\n\nQUESTION: {question}")
                parsed = _parse_llm_json(self._chat(_SYSTEM, prompt) or "")
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
        if self._wants_llm():
            try:
                system = (
                    "You write a short second-person music-taste profile for the "
                    f"archetype \"{arch['name']}\". Use ONLY the DATA: name the real "
                    "cluster/sound-bucket names and artists it contains, reusing those "
                    "labels VERBATIM (copy their exact words, don't paraphrase); "
                    "invent nothing.\n"
                    "Reply as a single JSON object with EXACTLY these fields, in this order:\n"
                    '  "thoughts": brief reasoning about what the DATA supports,\n'
                    '  "narrative": the profile shown to the visitor — 3-5 sentences, warm '
                    "but specific, plain prose, no markdown, no preamble, do not restate "
                    "the archetype name in the first sentence,\n"
                    '  "cited": a JSON array of the exact cluster/artist names your '
                    "narrative mentions.\n"
                    "Output only the JSON object.")
                parsed = _parse_llm_json(self._chat(system, f"DATA:\n{grounding}") or "")
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
