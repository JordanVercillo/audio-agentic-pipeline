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
from .prompt_contract import (
    TOOL_CONTRACT_VERSION,
    build_system,
    build_tool_system,
    is_empty_reply,
    reply_text,
    retry_hint,
    verify_citations,
)

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

_MAX_TOKENS = 1024  # a taste answer is deliberately short — well under stream/timeout limits

# A3 — the local Ollama path. gemma4:12b's 262K default context inflates the KV
# cache past a 12 GB card's free VRAM (measured 29% CPU spill); our grounding is
# ~2K tokens, so cap num_ctx to keep weights + KV fully on-GPU. format="json"
# grammar-constrains a thinking model's output to one JSON object (reasoning
# lands in the schema's `thoughts` field, not as loose prose).
_OLLAMA_NUM_CTX = 8192
# Cap generation so a THINKING model can't grind forever (K0.5). K1c reality:
# gemma4:12b runs to this cap (it pads with reasoning) → ~25 s/turn at 1024, and
# it is INCONSISTENT on the story task (sometimes a clean story, sometimes empty
# content — even warm, even with a directive). So the deterministic fallback is
# the reliability backbone (D-5); gemma4 enhances a turn when it succeeds fast.
# 1024 keeps turns responsive; a truncated/empty gemma4 reply → fallback, which
# is grounded and instant. Raising it only trades latency for marginal, still-
# inconsistent gains. The flywheel (D-47) + adapters (K5) are the real fix.
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


def _ollama_chat_messages(model: str, messages: list[dict]) -> Optional[str]:
    """Chat against the local Ollama server (A3, $0) with a full messages
    array — the K2c tool loop grows one per action/result turn. Returns the
    raw content string, or None on an unexpected shape. HTTP errors propagate —
    the caller guards and falls back deterministically."""
    import requests

    resp = requests.post(
        f"{config.ollama_host()}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "format": "json", "stream": False,
            "options": {"num_ctx": _OLLAMA_NUM_CTX,
                        "num_predict": _OLLAMA_NUM_PREDICT, "temperature": 0},
            "keep_alive": "10m",  # keep it resident so back-to-back asks are warm
        },
        timeout=_OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return (resp.json().get("message") or {}).get("content")


def _ollama_chat(model: str, system: str, prompt: str) -> Optional[str]:
    """Single-shot convenience wrapper over :func:`_ollama_chat_messages`."""
    return _ollama_chat_messages(model, [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}])


# K2.1 — defense-in-depth for EXTERNALLY-SOURCED strings interpolated into the
# grounding (track/artist names, genres: playlist imports make them attacker-
# reachable). The RTCROS contract already declares data-never-instructions;
# neutralizing makes the cheap injection shapes impossible to even RENDER —
# no angle brackets (no </data> breakout), no newlines (no forged grounding
# lines), capped length. Benign names pass through unchanged.
_UNSAFE_GROUNDING_CHARS = re.compile(r"[<>\r\n\t]")


def _neutralize(text: Any, cap: int = 160) -> str:
    s = _UNSAFE_GROUNDING_CHARS.sub(" ", str(text or ""))
    return re.sub(r"\s{2,}", " ", s).strip()[:cap]


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
        # our template sentences, but with untrusted names embedded upstream —
        # same neutralization, roomier cap (a legit sentence never needs <> or \n)
        lines.append(_neutralize(prof["message"], cap=240))
    for h in prof.get("highlights", []):
        lines.append(f"  - {_neutralize(h, cap=240)}")
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
            _neutralize(a["name"])
            + (f" [{_neutralize(a['genres'])}]" if a.get("genres") else "")
            for a in artists[:10])
        lines.append(f"Top artists: {alist}.")
    for rng in taste.get("ranges", []):
        tracks = rng.get("tracks", [])
        if tracks:
            tl = "; ".join(
                f"{_neutralize(t['name'])} — {_neutralize(t['artist'])}"
                + (" [in corpus]" if t.get("in_corpus") else "")
                for t in tracks[:8])
            lines.append(f"Top tracks ({rng['label']}): {tl}.")
    if glossary:
        lines.append("Feature glossary: "
                     + " ".join(f"{k} = {v}" for k, v in glossary.items()))
    return "\n".join(lines) if lines else _EMPTY_GROUNDING


class TasteRAG:
    """Grounded taste Q&A over the visitor's own retrieved data."""

    def __init__(self, feature_store: Any = None, model: Optional[str] = None,
                 tools_factory: Any = None) -> None:
        self.fs = feature_store
        self.model = model or config.rag_model()
        # K2c: how answer() gets its ChatDataTools. None = the real engine over
        # data/marts; tests inject a synthetic-marts factory (or one that raises
        # FileNotFoundError to pin the legacy single-shot path) so behavior
        # never depends on which machine has marts built.
        self.tools_factory = tools_factory

    def _wants_llm(self) -> bool:
        """True when a real model is configured: a local Ollama model (A3, no
        key) or an Anthropic model with a key. Otherwise the deterministic path."""
        return self.model.startswith("ollama:") or bool(config.anthropic_key())

    def _chat(self, system: str, prompt: str) -> Optional[str]:
        """Provider-agnostic single-shot chat → the raw reply text, or None."""
        return self._chat_messages(system, [{"role": "user", "content": prompt}])

    def _chat_messages(self, system: str, messages: list[dict]) -> Optional[str]:
        """Provider-agnostic MULTI-TURN chat (K2c — the tool loop grows the
        array one action/result pair per turn). `ollama:<model>` hits the local
        server ($0, A3); otherwise Anthropic (needs a key). May raise — callers
        guard and fall back."""
        if self.model.startswith("ollama:"):
            return _ollama_chat_messages(
                self.model.split(":", 1)[1],
                [{"role": "system", "content": system}, *messages])
        key = config.anthropic_key()
        if not key:
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=self.model, max_tokens=_MAX_TOKENS, system=system,
            messages=messages)
        if resp.stop_reason == "refusal":
            return None
        return next((b.text for b in resp.content if b.type == "text"), "")

    def _grounded_reply(self, mode: str, grounding: str, tail: str) -> Optional[dict[str, Any]]:
        """One RTCROS turn (D-48) with verify-and-retry. Returns {text, cited} or
        None to fall back. The teeth the probe demanded: an empty/unparseable
        reply → None (never ship blank); citations the model claimed but didn't
        say → ONE corrective retry against the grounding."""
        system = build_system(mode)
        user = f"<data>\n{grounding}\n</data>\n\n{tail}".rstrip()
        raw = self._chat(system, user) or ""
        parsed = _parse_llm_json(raw)
        if is_empty_reply(parsed, mode):
            return None
        v = verify_citations(parsed, grounding, mode)
        if not v["ok"]:
            raw2 = self._chat(system, user + retry_hint(v["missing"])) or ""
            retry = _parse_llm_json(raw2)
            if not is_empty_reply(retry, mode):
                parsed, raw = retry, raw2  # the retry is what the visitor saw
        return {"text": reply_text(parsed, mode), "raw": raw,
                "cited": [str(c) for c in parsed.get("cited") or []]}

    def story(self, taste: dict[str, Any]) -> dict[str, Any]:
        """The chat's opening: gemma4 develops the listener's DATA STORY (its
        strongest surface per the K1 probe). Returns {answer, source, model, …};
        falls back to the deterministic profile narrative if the model is absent
        or empty. Never raises."""
        glossary = self.fs.feature_glossary(_GLOSSARY_FEATURES) if self.fs else {}
        grounding = _grounding_text(taste, glossary)
        if self._wants_llm() and grounding != _EMPTY_GROUNDING:
            try:
                # gemma4 in chat mode returns EMPTY when the user turn is just
                # <data> with no instruction (verified live, K1c) — a directive
                # anchors the story task and it delivers.
                r = self._grounded_reply("story", grounding, "REQUEST: Write my data story now.")
                if r is not None:
                    return {"answer": r["text"], "source": "llm", "model": self.model,
                            "cited": r["cited"], "grounding": grounding, "raw": r["raw"]}
            except Exception as exc:  # noqa: BLE001 — never fail the page
                logger.warning("RAG story failed (%s) — deterministic fallback", exc)
        return {"answer": self._fallback(taste), "source": "fallback",
                "model": None, "grounding": grounding}

    # ── K2c: the flat JSON-action tool loop over the semantic marts ─────────
    _TOOL_MAX_DEPTH = 3   # query turns per user question; the answer turn is free

    def _tool_loop(self, question: str, grounding: str,
                   ) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
        """Drive the depth-3 flat-action loop (probe-validated, d36cf49).

        Returns ``(reply_or_None, meta)``. ``meta`` ALWAYS carries the
        transcript/raw/depth — a degraded turn preserves its tool transcript so
        the D-47 flywheel can cluster which queries failed (missing_fact).
        Raises only construction-level errors the caller treats as
        loop-unavailable (e.g. marts not built)."""
        from ..agent.chat_tools import MAX_ROWS, ChatDataTools
        factory = self.tools_factory or ChatDataTools
        meta: dict[str, Any] = {"depth": 0, "transcript": "", "raw": ""}
        with factory() as tools:
            card = tools.schema_card()
            system = build_tool_system(card, max_depth=self._TOOL_MAX_DEPTH,
                                       max_rows=MAX_ROWS)
            msgs: list[dict] = [{"role": "user",
                                 "content": f"<data>\n{grounding}\n</data>\n\n"
                                            f"QUESTION: {question}"}]
            # rendered_context for the review reader: grounding + schema + every
            # SQL and its rendered result, in order (D-47).
            transcript = [f"<data>\n{grounding}\n</data>", f"SCHEMA:\n{card}"]
            raws: list[str] = []

            def _meta() -> dict[str, Any]:
                meta.update(transcript="\n\n".join(transcript),
                            raw="\n---\n".join(raws))
                return meta

            for _ in range(self._TOOL_MAX_DEPTH + 1):
                raw = self._chat_messages(system, msgs) or ""
                raws.append(raw)
                act = _parse_llm_json(raw)
                if not isinstance(act, dict) or act.get("tool") not in ("query", "answer"):
                    return None, _meta()               # wedged — degrade honestly
                msgs.append({"role": "assistant", "content": raw})
                if act["tool"] == "answer":
                    ground_all = "\n".join(transcript)
                    if not reply_text(act, "adhoc"):
                        return None, _meta()
                    v = verify_citations(act, ground_all, "adhoc")
                    if not v["ok"]:                    # ONE corrective retry
                        msgs.append({"role": "user",
                                     "content": retry_hint(v["missing"])})
                        raw2 = self._chat_messages(system, msgs) or ""
                        raws.append(raw2)
                        retry = _parse_llm_json(raw2)
                        if retry and reply_text(retry, "adhoc"):
                            act = retry
                    return {"text": reply_text(act, "adhoc"),
                            "cited": [str(c) for c in act.get("cited") or []]}, _meta()
                # a query action: run guarded/clamped/watchdogged, feed back
                if meta["depth"] >= self._TOOL_MAX_DEPTH:
                    return None, _meta()               # budget spent — degrade
                meta["depth"] += 1
                rendered = tools.render_result(tools.run_query(str(act.get("sql", ""))))
                transcript.append(f"SQL: {act.get('sql', '')}\n{rendered}")
                msgs.append({"role": "user", "content": rendered})
            return None, _meta()                       # depth exhausted

    def answer(self, question: str, taste: dict[str, Any]) -> dict[str, Any]:
        """Return {answer, source, model}. Never raises — falls back deterministically.

        K2c: adhoc now runs the TOOL LOOP over the semantic marts (grounding
        stays in <data> for personal facts; library facts come from SQL). The
        loop degrades to the deterministic fallback WITH its transcript logged;
        marts-not-built degrades to the pre-K2c single-shot grounded path."""
        glossary = self.fs.feature_glossary(_GLOSSARY_FEATURES) if self.fs else {}
        grounding = _grounding_text(taste, glossary)
        # K0.5: an empty context has nothing to ground on — don't spend an LLM
        # call (and a possible cold-load timeout) to have it guess; the
        # deterministic fallback answers honestly from the retrieved facts (D-5).
        if grounding == _EMPTY_GROUNDING:
            return {"answer": self._fallback(taste), "source": "fallback",
                    "model": None, "grounding": grounding}
        if self._wants_llm():
            try:
                reply, meta = self._tool_loop(question, grounding)
                if reply is not None:
                    return {"answer": reply["text"], "source": "llm",
                            "model": self.model, "cited": reply["cited"],
                            "grounding": meta["transcript"], "raw": meta["raw"],
                            "depth": meta["depth"],
                            "prompt_version": TOOL_CONTRACT_VERSION}
                # loop degraded (bad action / empty / depth) → deterministic
                # fallback, transcript PRESERVED for the flywheel
                return {"answer": self._fallback(taste), "source": "fallback",
                        "model": None, "grounding": meta["transcript"],
                        "raw": meta["raw"], "depth": meta["depth"],
                        "prompt_version": TOOL_CONTRACT_VERSION,
                        "error": "tool_loop_degraded"}
            except FileNotFoundError:
                # marts not built (fresh checkout / tests) — the pre-K2c
                # single-shot grounded path still works
                try:
                    r = self._grounded_reply("adhoc", grounding,
                                             f"QUESTION: {question}")
                    if r is not None:
                        return {"answer": r["text"], "source": "llm",
                                "model": self.model, "cited": r["cited"],
                                "grounding": grounding, "raw": r["raw"]}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("RAG LLM answer failed (%s) — fallback", exc)
            except Exception as exc:  # noqa: BLE001 — an LLM error must never fail the request
                logger.warning("RAG tool loop failed (%s) — deterministic fallback", exc)
        return {"answer": self._fallback(taste), "source": "fallback",
                "model": None, "grounding": grounding}

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
        # D-48: the profile mode of the ONE contract — no second inline encoding.
        if self._wants_llm() and grounding != _EMPTY_GROUNDING:
            try:
                # a user directive anchors the task (empty user turn → empty
                # output; verified live, K1c).
                r = self._grounded_reply("profile", grounding, "REQUEST: Write my taste profile now.")
                if r is not None:
                    return {"name": arch["name"], "narrative": r["text"],
                            "cited": r["cited"], "source": "llm", "model": self.model,
                            "grounding": grounding, "raw": r["raw"]}
            except Exception as exc:  # noqa: BLE001 — never fail the page
                logger.warning("classify LLM failed (%s) — deterministic narrative", exc)
        return {"name": arch["name"], "narrative": self._archetype_narrative(taste),
                "source": "fallback", "model": None, "grounding": grounding}

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
