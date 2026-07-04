"""
portfolio.py — Single-file taste report renderer (SPEC P4)
===========================================================
Pure render logic: insights dict + artifact PNGs + fact table → one
self-contained HTML string (inline CSS, base64 ``data:`` images — no external
assets, opens offline).

Orchestration (regenerating the inputs from a fresh gold layer) lives in
``scripts/build_report.py``; this module only reads and renders. Autoescape
is ON — track/artist names are untrusted strings (P8 will render OTHER
users' libraries through this same template).
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"
ARTIFACTS_DIR = _PROJECT_ROOT / "artifacts"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# artifact filename → template image slot
REPORT_IMAGES = {
    "taste_map": "taste_map.png",
    "drift_radar": "drift_radar.png",
    "temporal_heatmap": "temporal_heatmap.png",
    "feature_distributions": "feature_distributions.png",
    "artist_flow": "artist_flow.png",
}

_WINDOWS = [
    ("short", "short_term", "Last 4 Weeks"),
    ("medium", "medium_term", "Last 6 Months"),
    ("long", "long_term", "All Time"),
]

_SUPERLATIVE_TITLES = {
    "highest_energy": "Highest energy",
    "fastest": "Fastest",
    "most_acoustic": "Most acoustic",
    "brightest": "Brightest",
}

_WINDOW_SHORT = {"short_term": "4 wks", "medium_term": "6 mo", "long_term": "All"}


def _b64_data_uri(path: Path) -> str:
    """Encode an image file as a self-contained data: URI."""
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def top_tracks_by_window(fact: pd.DataFrame, top_n: int = 10) -> list[dict]:
    """Top-N tracks per time window by listening rank (template-shaped)."""
    out = []
    for key, tr, title in _WINDOWS:
        subset = fact[fact["time_range"] == tr]
        if subset.empty or "rank" not in subset.columns:
            continue
        rows = subset.sort_values("rank").head(top_n)
        out.append({
            "key": key,
            "title": title,
            "tracks": [
                {"track_name": str(r.get("track_name", "?")),
                 "artist": str(r.get("primary_artist_name", "?"))}
                for _, r in rows.iterrows()
            ],
        })
    return out


def _shape_superlatives(superlatives: dict) -> list[dict]:
    """insights['superlatives'] → template-shaped list."""
    shaped = []
    for key, entries in superlatives.items():
        shaped.append({
            "title": _SUPERLATIVE_TITLES.get(key, key),
            "entries": [
                {"window": _WINDOW_SHORT.get(tr, tr),
                 "track_name": e["track_name"], "artist": e["artist"]}
                for tr, e in entries.items()
            ],
        })
    return shaped


def render_html(
    insights: dict,
    images: dict[str, str],
    top_tracks: list[dict],
) -> str:
    """
    Render the report. ``images`` values must already be data: URIs —
    the template never references the filesystem or the network.
    """
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("portfolio.html")

    genres = [
        {"name": name, "count": count}
        for name, count in sorted(
            insights.get("genres", {}).get("distribution", {}).items(),
            key=lambda kv: -kv[1],
        )
    ]

    return template.render(
        generated_at=insights.get("generated_at", ""),
        corpus=insights["corpus"],
        drift=insights["drift"],
        clusters=insights.get("clusters", {"available": False, "clusters": []}),
        persistence=insights["persistence"],
        superlatives=_shape_superlatives(insights.get("superlatives", {})),
        genres=genres,
        top_tracks=top_tracks,
        images=images,
    )


def build_report_html(
    modeled_dir: Optional[Union[str, Path]] = None,
    artifacts_dir: Optional[Union[str, Path]] = None,
    out_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Read insights.json + PNGs + the fact table, write the single-file report.

    Raises FileNotFoundError with a pointed message when an input is missing
    (the orchestrating script regenerates inputs first; direct callers get
    told exactly what to run).
    """
    modeled_dir = Path(modeled_dir or MODELED_DIR)
    artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
    out_path = Path(out_path or artifacts_dir / "taste_report.html")

    insights_path = artifacts_dir / "insights.json"
    if not insights_path.exists():
        raise FileNotFoundError(
            f"{insights_path} missing — run scripts/build_insights.py first")
    insights = json.loads(insights_path.read_text(encoding="utf-8"))

    images = {}
    for slot, filename in REPORT_IMAGES.items():
        png = artifacts_dir / filename
        if not png.exists():
            raise FileNotFoundError(
                f"{png} missing — run scripts/build_taste_map.py and "
                f"scripts/build_trend_charts.py first")
        images[slot] = _b64_data_uri(png)

    fact_path = modeled_dir / "fact_listening_features.parquet"
    if not fact_path.exists():
        raise FileNotFoundError(f"{fact_path} missing — run the pipeline first")
    fact = pd.read_parquet(fact_path, engine="pyarrow")

    html = render_html(insights, images, top_tracks_by_window(fact))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"   ✅ taste_report.html ({size_mb:.2f} MB, self-contained) → {out_path}")
    if size_mb > 10:
        print("   ⚠️  Report exceeds the 10 MB acceptance budget — "
              "reduce chart DPI or image count.")
    return out_path
