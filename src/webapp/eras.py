"""The era view — two well-documented industry stories, measured on this corpus.

`album_release_date` was captured for the whole corpus by D-70 and read by
exactly one surface. Grouped by decade against the MEASURED columns it answers
two questions a non-specialist immediately recognises:

  - **the loudness war** — records have been mastered louder every decade
  - **the streaming squeeze** — songs have got shorter

Both come out of `era_profile.parquet` with no new acquisition.

## The honesty this page has to carry

This is **one person's library**, not a sample of recorded music. The 1970s
bucket is "the 1970s tracks Jordan listens to", which is a different and much
narrower thing than "1970s music". The direction of both trends matches the
published literature; the magnitudes are this corpus's, and the page says so
rather than implying a survey.

Two further caveats stated on the page rather than silently corrected:
`release_date` is Spotify's, so a remaster reads as its REISSUE year (D-61),
and `loudness_db` is measured from OUR acquired audio, so a loud YouTube
transfer of a quiet master reads loud.
"""
from __future__ import annotations

from typing import Any, Optional

# Under this many tracks a decade is a handful of songs, not a period.
MIN_TRACKS = 20


def era_rows(era_df) -> list[dict[str, Any]]:
    """The mart as plain dicts, oldest first, thin decades already dropped."""
    if era_df is None or getattr(era_df, "empty", True):
        return []
    rows = era_df.to_dict("records")
    return [r for r in sorted(rows, key=lambda r: r["decade"])
            if r.get("n_tracks", 0) >= MIN_TRACKS]


def era_summary(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The two headline deltas, DERIVED from the first and last decade shown.

    Never hard-coded: the corpus grows, and a typed "+4.1 dB" would be wrong
    within a week — the failure this project spent a session removing from its
    README.
    """
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    d_loud = last["mean_loudness_db"] - first["mean_loudness_db"]
    d_dur = last["mean_duration_sec"] - first["mean_duration_sec"]
    return {
        "from_decade": int(first["decade"]), "to_decade": int(last["decade"]),
        "loudness_delta_db": round(d_loud, 2),
        "duration_delta_sec": round(d_dur, 1),
        "louder": d_loud > 0,
        "shorter": d_dur < 0,
        "n_total": sum(int(r["n_tracks"]) for r in rows),
        "n_decades": len(rows),
    }


def _scale(value: float, lo: float, hi: float) -> float:
    return 0.0 if hi == lo else (value - lo) / (hi - lo)


def era_chart_svg(rows: list[dict[str, Any]], column: str, label: str, unit: str,
                  width: int = 620, height: int = 230) -> str:
    """A bare-bones line+point chart. No JS, no chart library, no external CSS.

    Axis choice worth stating: the y-range is the DATA's range with a small pad,
    not zero-based. For dBFS a zero-based axis is meaningless (0 dBFS is digital
    full scale, which no music sits near) and it would flatten a real 4 dB move
    into a hairline. The page prints the actual numbers under the chart so the
    shape can never be the only evidence.
    """
    if len(rows) < 2:
        return ""
    vals = [float(r[column]) for r in rows]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1.0
    lo, hi = lo - pad, hi + pad
    pad_l, pad_r, pad_t, pad_b = 58, 16, 18, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    pts = []
    for i, r in enumerate(rows):
        x = pad_l + (plot_w * (i / (len(rows) - 1)))
        y = pad_t + plot_h * (1 - _scale(float(r[column]), lo, hi))
        pts.append((x, y, r))

    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="era-chart" role="img" '
        f'aria-label="{label} by decade">',
        f'<title>{label} by decade</title>',
    ]
    # baseline + top gridline with their values, so the axis is readable
    for frac, val in ((0.0, hi), (1.0, lo)):
        y = pad_t + plot_h * frac
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" class="era-grid"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" '
                     f'class="era-axis">{val:.1f}</text>')
    parts.append('<polyline class="era-line" points="'
                 + " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts) + '"/>')
    for x, y, r in pts:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="era-dot">'
                     f'<title>{int(r["decade"])}s — {float(r[column]):.2f}{unit} '
                     f'({int(r["n_tracks"])} tracks)</title></circle>')
        parts.append(f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle" '
                     f'class="era-axis">{int(r["decade"])}s</text>')
    parts.append("</svg>")
    return "".join(parts)


def structure_facts(summary_df) -> Optional[dict[str, Any]]:
    """Corpus-level statements the SECTION grain makes possible.

    `changes_key` is the one worth understanding: it cannot be computed from a
    track-grain table at all. It is not a property of a track — it is a property
    of how a track's parts differ from each other, and expressing it needs a
    second fact table at (track, section) grain. That is the whole argument for
    the extra grain, in one column.
    """
    if summary_df is None or getattr(summary_df, "empty", True):
        return None
    n = len(summary_df)
    if n == 0:
        return None
    return {
        "n_tracks": int(n),
        "n_sections": int(summary_df["n_sections"].sum()),
        "mean_sections": round(float(summary_df["n_sections"].mean()), 2),
        "pct_change_key": round(float(summary_df["changes_key"].mean()) * 100, 1),
        "pct_change_mode": round(float(summary_df["changes_mode"].mean()) * 100, 1),
        "median_loudness_range_db": round(
            float(summary_df["loudness_range_db"].median()), 1),
        "median_section_sec": round(float(summary_df["mean_section_sec"].median()), 1),
    }
