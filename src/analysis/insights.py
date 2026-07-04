"""
insights.py — The Insight Engine (SPEC P2)
===========================================
Turns the gold layer into a stable, agent-consumable ``insights.json`` and a
human-readable ``INSIGHTS.md`` — pipeline step 8.

Design rules (SPEC D-5, deterministic-first):
    - Every number in the outputs comes from pure functions over warehouse
      DataFrames — same warehouse in, same JSON out. Fully unit-testable on
      synthetic frames.
    - The optional LLM polish (``--llm-polish``) ADDS an executive-summary
      prose section generated from the JSON; it never rewrites the
      deterministic sections, and any failure (no SDK, no credentials, API
      error) silently degrades to the pure-template output.
    - The JSON schema is versioned (``schema_version``). P5's MCP
      ``get_insights()`` tool and P8's RAG layer read this file — treat key
      renames/removals as breaking changes that bump the version.

Inputs (all Parquet, all optional except the fact table):
    modeled/fact_listening_features.parquet   (required — drift, superlatives)
    modeled/cluster_assignments.parquet       (optional — taste-map clusters)
    cleansed/cleansed_features.parquet        (optional — acoustic cluster labels)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from src.analysis.clustering import UNKNOWN_BUCKET, describe_clusters
from src.analysis.drift import compute_taste_drift

logger = logging.getLogger(__name__)

INSIGHTS_SCHEMA_VERSION = 1

# ── Default paths ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLEANSED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "cleansed"
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"
ARTIFACTS_DIR = _PROJECT_ROOT / "artifacts"

# Superlatives: (json_key, fact column, human label, direction)
_SUPERLATIVE_SPECS = [
    ("highest_energy", "rms_mean", "Highest energy", "max"),
    ("fastest", "tempo_bpm", "Fastest", "max"),
    ("most_acoustic", "harmonic_ratio", "Most acoustic", "max"),
    ("brightest", "spectral_centroid_mean", "Brightest", "max"),
]

_TIME_RANGE_ORDER = ["short_term", "medium_term", "long_term"]
_TIME_RANGE_LABELS = {
    "short_term": "Last 4 weeks",
    "medium_term": "Last 6 months",
    "long_term": "All time",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION BUILDERS (pure: DataFrames in → JSON-able dicts out)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_corpus_section(
    fact: pd.DataFrame,
    assignments: Optional[pd.DataFrame],
) -> dict:
    """Corpus-level stats: sizes, feature/genre coverage, time ranges."""
    unique_tracks = fact["spotify_track_id"].nunique()
    with_features = (
        int(fact.drop_duplicates("spotify_track_id")["rms_mean"].notna().sum())
        if "rms_mean" in fact.columns else 0
    )
    genre_covered = (
        int((assignments["genre_bucket"] != UNKNOWN_BUCKET).sum())
        if assignments is not None and "genre_bucket" in assignments.columns else None
    )
    return {
        "n_fact_rows": int(len(fact)),
        "n_unique_tracks": int(unique_tracks),
        "n_tracks_with_features": with_features,
        "n_unique_artists": (
            int(fact["primary_artist_name"].nunique())
            if "primary_artist_name" in fact.columns else None
        ),
        "time_ranges": sorted(
            fact["time_range"].unique().tolist(),
            key=lambda tr: _TIME_RANGE_ORDER.index(tr) if tr in _TIME_RANGE_ORDER else 99,
        ),
        "genre_coverage": (
            {"covered": genre_covered, "total": int(len(assignments))}
            if genre_covered is not None else None
        ),
    }


def build_drift_section(fact: pd.DataFrame) -> dict:
    """Taste drift: score, label, stability, pairwise, top-5 drivers."""
    results = compute_taste_drift(fact)
    deltas: pd.DataFrame = results["feature_deltas"]
    top_drivers = (
        deltas.head(5)[
            ["feature", "label", "short_term", "long_term",
             "relative_delta_pct", "direction"]
        ].to_dict(orient="records")
        if not deltas.empty else []
    )
    return {
        "score": round(float(results["drift_score"]), 4),
        "label": results["drift_label"],
        "stability_score": round(float(results["stability_score"]), 4),
        "pairwise_distances": {k: round(float(v), 4)
                               for k, v in results["pairwise_distances"].items()},
        "top_drivers": top_drivers,
    }


def build_clusters_section(
    assignments: Optional[pd.DataFrame],
    features: Optional[pd.DataFrame],
) -> dict:
    """
    Taste-map cluster summaries. ``available: False`` (schema-stable) when the
    taste map hasn't been built. Acoustic labels are recomputed by joining
    stored cluster_ids onto the feature table — no re-clustering happens here.
    """
    if assignments is None or assignments.empty or "cluster_id" not in assignments.columns:
        return {"available": False, "k": None, "clusters": []}

    frame = assignments.copy()
    if features is not None and not features.empty:
        frame = frame.merge(features, on="spotify_track_id", how="left", suffixes=("", "_f"))

    summary = describe_clusters(frame)
    return {
        "available": True,
        "k": int(frame["cluster_id"].nunique()),
        "clusters": summary.to_dict(orient="records"),
    }


def build_persistence_section(fact: pd.DataFrame, top_n: int = 5) -> dict:
    """Cross-range persistence: how much of the taste survives across windows."""
    per_track = fact.groupby("spotify_track_id").agg(
        n_ranges=("time_range", "nunique"),
        avg_rank=("rank", "mean") if "rank" in fact.columns else ("time_range", "size"),
        track_name=("track_name", "first"),
        artist=("primary_artist_name", "first")
        if "primary_artist_name" in fact.columns else ("track_name", "first"),
    ).reset_index()

    counts = per_track["n_ranges"].value_counts().to_dict()
    favorites = (
        per_track[per_track["n_ranges"] == 3]
        .sort_values("avg_rank")
        .head(top_n)
    )
    return {
        "n_single_range": int(counts.get(1, 0)),
        "n_two_ranges": int(counts.get(2, 0)),
        "n_all_three": int(counts.get(3, 0)),
        "persistent_favorites": [
            {"track_name": str(r.track_name), "artist": str(r.artist),
             "avg_rank": round(float(r.avg_rank), 1)}
            for r in favorites.itertuples()
        ],
    }


def build_superlatives_section(fact: pd.DataFrame) -> dict:
    """Per-time-range acoustic superlatives (argmax over DSP features)."""
    out: dict = {}
    for key, col, _label, direction in _SUPERLATIVE_SPECS:
        if col not in fact.columns:
            continue
        entries = {}
        for tr in [t for t in _TIME_RANGE_ORDER if t in fact["time_range"].unique()]:
            subset = fact[(fact["time_range"] == tr) & fact[col].notna()]
            if subset.empty:
                continue
            row = subset.loc[subset[col].idxmax() if direction == "max" else subset[col].idxmin()]
            entries[tr] = {
                "track_name": str(row.get("track_name", "?")),
                "artist": str(row.get("primary_artist_name", "?")),
                "value": round(float(row[col]), 4),
            }
        if entries:
            out[key] = entries
    return out


def build_genres_section(assignments: Optional[pd.DataFrame], fact: pd.DataFrame) -> dict:
    """Genre-bucket distribution + most-listened artists."""
    distribution = (
        assignments["genre_bucket"].value_counts().to_dict()
        if assignments is not None and "genre_bucket" in assignments.columns else {}
    )
    top_artists = []
    if "primary_artist_name" in fact.columns:
        counts = (
            fact.drop_duplicates("spotify_track_id")["primary_artist_name"]
            .value_counts().head(5)
        )
        top_artists = [{"artist": str(a), "n_tracks": int(n)} for a, n in counts.items()]
    return {
        "distribution": {str(k): int(v) for k, v in distribution.items()},
        "top_artists": top_artists,
    }


def build_insights(
    fact: pd.DataFrame,
    assignments: Optional[pd.DataFrame] = None,
    features: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Assemble the full insights document from warehouse DataFrames.

    Pure orchestration of the section builders — no I/O. The top-level key
    set is the schema contract; see INSIGHTS_SCHEMA_VERSION.
    """
    if fact.empty or "time_range" not in fact.columns:
        raise ValueError("fact table is empty or missing time_range — run the pipeline first")

    return {
        "schema_version": INSIGHTS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": build_corpus_section(fact, assignments),
        "drift": build_drift_section(fact),
        "clusters": build_clusters_section(assignments, features),
        "persistence": build_persistence_section(fact),
        "superlatives": build_superlatives_section(fact),
        "genres": build_genres_section(assignments, fact),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MARKDOWN RENDERER (deterministic template)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def render_markdown(insights: dict, executive_summary: Optional[str] = None) -> str:
    """Render the insights dict to INSIGHTS.md. Same dict in, same text out."""
    c, d = insights["corpus"], insights["drift"]
    lines: list[str] = [
        "# 🎧 Taste Insights",
        "",
        f"*Generated {insights['generated_at']} · schema v{insights['schema_version']} · "
        f"{c['n_unique_tracks']} tracks / {c['n_fact_rows']} listening entries / "
        f"{c['n_tracks_with_features']} with 77-dim DSP features*",
        "",
    ]

    if executive_summary:
        lines += ["## Executive summary", "", executive_summary.strip(), "",
                  "*(narrative generated by LLM from the deterministic metrics below)*", ""]

    # ── Drift ──
    lines += [
        "## The drift verdict",
        "",
        f"**Taste Drift Score: {d['score']}σ** — {d['label']}",
        "",
        "*(RMS per-feature shift between your recent and all-time acoustic "
        "centroids, in standard-deviation units)*",
        "",
        f"Stability score: {d['stability_score']} · Pairwise distances: "
        + " · ".join(f"{k.replace('_vs_', ' → ')}: {v}"
                     for k, v in d["pairwise_distances"].items()),
        "",
    ]
    if d["top_drivers"]:
        lines += ["**What's driving it** (short-term vs all-time):", "",
                  "| Feature | Short term | All time | Δ | Direction |",
                  "|---|---|---|---|---|"]
        for drv in d["top_drivers"]:
            lines.append(
                f"| {drv['label']} | {drv['short_term']} | {drv['long_term']} "
                f"| {drv['relative_delta_pct']}% | {drv['direction']} |")
        lines.append("")

    # ── Clusters ──
    cl = insights["clusters"]
    if cl["available"]:
        lines += [f"## The neighborhoods (k={cl['k']})", "",
                  "| Cluster | Tracks | Acoustic character | Mostly | Top artist |",
                  "|---|---|---|---|---|"]
        for row in cl["clusters"]:
            lines.append(
                f"| {row['cluster_id']} | {row['n_tracks']} | {row['acoustic_label']} "
                f"| {row['dominant_genre']} | {row['top_artist']} |")
        lines += ["", "*(see `artifacts/taste_map.png` for the map)*", ""]

    # ── Persistence ──
    p = insights["persistence"]
    lines += [
        "## Staying power",
        "",
        f"- Tracks in one time range only: **{p['n_single_range']}**",
        f"- In two ranges: **{p['n_two_ranges']}**",
        f"- In all three (persistent favorites): **{p['n_all_three']}**",
        "",
    ]
    if p["persistent_favorites"]:
        lines += ["The all-timers:", ""]
        lines += [f"1. **{f['track_name']}** — {f['artist']} (avg rank {f['avg_rank']})"
                  for f in p["persistent_favorites"]]
        lines.append("")

    # ── Superlatives ──
    s = insights["superlatives"]
    if s:
        lines += ["## Superlatives", ""]
        titles = {k: label for k, _c, label, _d in _SUPERLATIVE_SPECS}
        for key, entries in s.items():
            lines.append(f"**{titles.get(key, key)}:**")
            for tr, e in entries.items():
                lines.append(f"- {_TIME_RANGE_LABELS.get(tr, tr)}: "
                             f"*{e['track_name']}* — {e['artist']} ({e['value']})")
            lines.append("")

    # ── Genres ──
    g = insights["genres"]
    if g["distribution"]:
        dist = " · ".join(f"{k}: {v}" for k, v in
                          sorted(g["distribution"].items(), key=lambda kv: -kv[1]))
        lines += ["## Genre profile", "", dist, ""]
    if g["top_artists"]:
        lines += ["Most-collected artists: "
                  + ", ".join(f"**{a['artist']}** ({a['n_tracks']})"
                              for a in g["top_artists"]), ""]

    lines += ["---", "*Vercillo Analytics — deterministic insight engine "
              "(`src/analysis/insights.py`); acoustic features from local DSP, "
              "not vendor APIs.*", ""]
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OPTIONAL LLM POLISH (additive, never load-bearing — SPEC D-5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def llm_polish(insights: dict, model: Optional[str] = None) -> Optional[str]:
    """
    Generate a short executive-summary narrative from the insights JSON.

    Returns the prose, or None on ANY failure (SDK missing, no credentials,
    API error) — callers proceed with the deterministic output unchanged.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("--llm-polish requested but the 'anthropic' SDK is not "
                       "installed (pip install anthropic) — skipping polish.")
        return None

    model = model or os.environ.get("INSIGHTS_LLM_MODEL", "claude-opus-4-8")
    # Only the metric sections — keep the prompt small and grounded.
    context = {k: insights[k] for k in
               ("corpus", "drift", "clusters", "persistence", "superlatives", "genres")}

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=(
                "You write short, engaging executive summaries of music-taste "
                "analytics. Use ONLY facts and numbers present in the provided "
                "JSON — never invent values. 120-180 words, second person "
                "('your taste'), no headings, no bullet lists."
            ),
            messages=[{
                "role": "user",
                "content": "Summarize this listener's taste profile:\n\n"
                           + json.dumps(context, indent=2),
            }],
        )
        if response.stop_reason == "refusal":
            logger.warning("LLM polish refused — using deterministic output.")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        return text.strip() or None
    except Exception as exc:  # noqa: BLE001 — polish must never break the pipeline
        logger.warning("LLM polish failed (%s) — using deterministic output.", exc)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  I/O WRAPPER (pipeline step 8 entry point)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _read_optional(path: Path) -> Optional[pd.DataFrame]:
    return pd.read_parquet(path, engine="pyarrow") if path.exists() else None


def build_and_write_insights(
    modeled_dir: Optional[Union[str, Path]] = None,
    cleansed_dir: Optional[Union[str, Path]] = None,
    out_dir: Optional[Union[str, Path]] = None,
    polish: bool = False,
) -> dict:
    """
    Warehouse → artifacts/insights.json + artifacts/INSIGHTS.md.

    Returns the insights dict. Raises FileNotFoundError when the fact table
    is absent (callers/step 8 decide whether that's a skip or an error).
    """
    modeled_dir = Path(modeled_dir or MODELED_DIR)
    cleansed_dir = Path(cleansed_dir or CLEANSED_DIR)
    out_dir = Path(out_dir or ARTIFACTS_DIR)

    fact_path = modeled_dir / "fact_listening_features.parquet"
    if not fact_path.exists():
        raise FileNotFoundError(f"Fact table not found: {fact_path}")

    fact = pd.read_parquet(fact_path, engine="pyarrow")
    assignments = _read_optional(modeled_dir / "cluster_assignments.parquet")
    features = _read_optional(cleansed_dir / "cleansed_features.parquet")

    insights = build_insights(fact, assignments=assignments, features=features)
    summary = llm_polish(insights) if polish else None
    markdown = render_markdown(insights, executive_summary=summary)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "insights.json"
    md_path = out_dir / "INSIGHTS.md"
    json_path.write_text(json.dumps(insights, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    print(f"   ✅ insights.json (schema v{insights['schema_version']}) → {json_path.name}")
    print(f"   ✅ INSIGHTS.md ({'LLM-polished' if summary else 'deterministic'}) → {md_path.name}")
    return insights
