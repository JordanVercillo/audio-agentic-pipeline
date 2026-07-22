"""
semantic.py — the "Talk to your data" semantic layer (D-49, Epic-K data floor).

Governed, analyst-facing marts materialized FROM the serving cache (the source
of truth — journal #35: the star schema is a second plane and drifts). Built in
the post-drain hook next to rebuild_marts, atomic-replace, idempotent. The chat
grounds on these; the frozen star schema stays the batch showcase and the chat
never reads it.

Views (this module): feature_dictionary (the metric/dimension contract with the
never-say caveats), track_card (per bridge key, with the feature_valid safety
gate), artist_rollup (per primary_artist_id — NEVER by name). cluster_profile
lands with the cluster-coverage decision.

Retrieval posture (D-49): NO embeddings — every question here is SQL-addressable
by a stable key, and a vector search can miss the true max. Bridge key is the
retrieval key; population_n travels on every percentile so a rank is never
mistaken across a rebuild.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .perceptual import CATALOG, _pct, _write_atomic

# feature_valid gate (D-49 / D-52 pre-echo): a broken/silent extraction reads
# tempo 0 and loudness ≈ −180 dBFS. Exclude ONLY the clearly-broken — never a
# legit long DJ mix — so "slowest/quietest song" can't answer with a dead row.
_MIN_VALID_TEMPO = 1.0
_MIN_VALID_LOUDNESS_DB = -80.0

# Analyst-contract enrichments of CATALOG, keyed by column: the ladder layer,
# what "higher" means, and the NEVER-SAY caveat (rule 3 becomes a row the model
# is handed, not tribal knowledge). Percentile-calibrated 0–1 features are their
# own rank, so percentile_source is None for them; measured raw values get a
# _pct rank column in track_card and point at it here.
_DICT_EXTRA: dict[str, dict[str, Any]] = {
    "tempo": {"layer": "measured", "direction": "higher = faster",
              "percentile_source": "tempo_pct", "caveat": ""},
    "key": {"layer": "measured", "direction": "categorical — no order",
            "percentile_source": None, "caveat": "0=C … 11=B; not orderable."},
    "mode": {"layer": "measured", "direction": "1 = major, 0 = minor",
             "percentile_source": None, "caveat": "categorical, not a magnitude."},
    "duration_sec": {"layer": "measured", "direction": "higher = longer",
                     "percentile_source": "duration_sec_pct", "caveat": ""},
    "loudness_db": {"layer": "measured", "direction": "higher = louder",
                    "percentile_source": "loudness_db_pct",
                    "caveat": "dBFS ≤ 0; a broken extraction reads ≈ −180 — see feature_valid."},
    "time_signature": {"layer": "measured", "direction": "beats per bar",
                       "percentile_source": None,
                       "caveat": "coarse: duple meter is reported as 4."},
    "energy": {"layer": "derived", "direction": "higher = more intense",
               "percentile_source": None, "caveat": ""},
    "danceability": {"layer": "derived", "direction": "higher = more danceable",
                     "percentile_source": None, "caveat": ""},
    "acousticness": {"layer": "derived", "direction": "higher = more acoustic",
                     "percentile_source": None, "caveat": ""},
    "speechiness": {"layer": "derived", "direction": "higher = more spoken-word",
                    "percentile_source": None, "caveat": ""},
    "brightness": {"layer": "derived", "direction": "higher = brighter",
                   "percentile_source": None, "caveat": ""},
    "punch": {"layer": "derived", "direction": "higher = harder attack",
              "percentile_source": None, "caveat": ""},
    "dynamics": {"layer": "derived", "direction": "higher = more variable",
                 "percentile_source": None, "caveat": ""},
    "valence_proxy": {"layer": "experimental", "direction": "higher = brighter mood",
                      "percentile_source": None,
                      "caveat": "a heuristic proxy, not a trained model — directional only."},
}

# Not in CATALOG (it's Spotify metadata, not a DSP feature) but the analyst sees
# it and MUST be told what it is — the load-bearing rule-3 caveat.
_POPULARITY_ROW = {
    "column": "popularity", "friendly": "Popularity", "tier": "context",
    "unit": "0–100", "layer": "metadata", "direction": "higher = more streamed",
    "percentile_source": None,
    "description": "Spotify's streaming popularity for the track.",
    "caveat": "Spotify METADATA, not acoustics — never describe how the music SOUNDS "
              "from it, and never use it as a model input.",
}


def feature_dictionary_frame() -> pd.DataFrame:
    """The unified metric/dimension contract (D-49): CATALOG + analyst fields +
    the popularity context row. One governed dictionary the chat is handed."""
    rows: list[dict[str, Any]] = []
    for c in CATALOG:
        extra = _DICT_EXTRA.get(c["column"], {})
        rows.append({
            "column": c["column"], "friendly": c["friendly"], "tier": c["tier"],
            "unit": c["unit"], "layer": extra.get("layer", "raw_dsp"),
            "direction": extra.get("direction", ""),
            "percentile_source": extra.get("percentile_source"),
            "description": c["description"], "caveat": extra.get("caveat", ""),
        })
    rows.append(dict(_POPULARITY_ROW))
    return pd.DataFrame(rows)


def build_track_card(cache: Any, perceptual_df: pd.DataFrame) -> pd.DataFrame:
    """Per-bridge-key analyst card: the perceptual features + metadata + a
    feature_valid gate + percentile ranks for the measured raw values. Keyed by
    spotify_track_id; a rebuild recomputes values, never keys (journal #35)."""
    if perceptual_df is None or perceptual_df.empty:
        return pd.DataFrame()
    df = perceptual_df.copy()
    meta = {r["id"]: r for r in cache.library_rows()}
    df["name"] = df["spotify_track_id"].map(lambda t: (meta.get(t) or {}).get("name") or t)
    df["artist"] = df["spotify_track_id"].map(lambda t: (meta.get(t) or {}).get("artist") or "")
    df["popularity"] = df["spotify_track_id"].map(lambda t: (meta.get(t) or {}).get("popularity"))
    df["duplicate_of"] = df["spotify_track_id"].map(
        lambda t: (meta.get(t) or {}).get("duplicate_of"))
    # the safety gate: clearly-broken extractions are excluded from superlatives
    df["feature_valid"] = (df["tempo"] > _MIN_VALID_TEMPO) & \
                          (df["loudness_db"] > _MIN_VALID_LOUDNESS_DB)
    # percentile ranks for the measured raw values (the 0–1 derived features are
    # already ranks). Ranked over VALID rows only, so a dead row can't skew them.
    valid = df["feature_valid"]
    for col in ("tempo", "loudness_db", "duration_sec"):
        ranks = pd.Series(pd.NA, index=df.index, dtype="Float64")
        if valid.any():
            ranks.loc[valid] = _pct(df.loc[valid, col]).round(4)
        df[f"{col}_pct"] = ranks
    return df


def build_artist_rollup(cache: Any, perceptual_df: pd.DataFrame) -> pd.DataFrame:
    """Per-artist analyst rollup, keyed by primary_artist_id (NEVER by name —
    names collide and rename; the id is stable since P3.1). Genres from the
    stored artist_meta; acoustic means over the artist's analyzed tracks."""
    rows_meta = cache.library_rows()          # carries primary_artist_id (D-49)
    ameta = cache.all_artist_meta()           # {artist_id: {artist_name, genres, ...}}
    perc = {} if perceptual_df is None or perceptual_df.empty else {
        r["spotify_track_id"]: r for _, r in perceptual_df.iterrows()}
    groups: dict[str, dict[str, Any]] = {}
    for m in rows_meta:
        paid = m.get("primary_artist_id")
        if not paid:
            continue
        g = groups.setdefault(paid, {"tracks": 0, "analyzed": 0,
                                     "energy": [], "tempo": [],
                                     "name": (m.get("artist") or "").split(",")[0].strip()})
        g["tracks"] += 1
        p = perc.get(m["id"])
        if p is not None:
            g["analyzed"] += 1
            g["energy"].append(float(p["energy"]))
            g["tempo"].append(float(p["tempo"]))
    rows: list[dict[str, Any]] = []
    for paid, g in groups.items():
        am = ameta.get(paid, {})
        rows.append({
            "primary_artist_id": paid,
            "artist_name": am.get("artist_name") or g["name"],
            "genres": am.get("genres") or "",
            "popularity": am.get("popularity"),
            "n_tracks": g["tracks"], "n_analyzed": g["analyzed"],
            "mean_energy": round(sum(g["energy"]) / len(g["energy"]), 4) if g["energy"] else None,
            "mean_tempo": round(sum(g["tempo"]) / len(g["tempo"]), 1) if g["tempo"] else None,
        })
    rows.sort(key=lambda r: (-r["n_analyzed"], -r["n_tracks"]))
    return pd.DataFrame(rows)


def build_corpus_facts(track_card: pd.DataFrame,
                       artist_rollup: pd.DataFrame) -> pd.DataFrame:
    """One-row corpus-facts mart (K2.0): the analyst's totals, derived from the
    frames this rebuild already built — no recompute. Acoustic stats run over
    feature_valid rows only, so a dead extraction can't tilt a corpus mean;
    counts report the invalid rows honestly instead of hiding them."""
    if track_card is None or track_card.empty:
        return pd.DataFrame()
    valid = track_card[track_card["feature_valid"]]

    def _stat(series: pd.Series, fn: str, ndigits: int) -> float | None:
        return None if valid.empty else round(float(getattr(series, fn)()), ndigits)

    return pd.DataFrame([{
        "n_tracks": int(len(track_card)),
        "n_feature_valid": int(track_card["feature_valid"].sum()),
        "n_artists": 0 if artist_rollup is None or artist_rollup.empty
        else int(len(artist_rollup)),
        "total_hours": _stat(valid["duration_sec"] / 3600.0, "sum", 2),
        "mean_duration_sec": _stat(valid["duration_sec"], "mean", 1),
        "median_duration_sec": _stat(valid["duration_sec"], "median", 1),
        "median_tempo": _stat(valid["tempo"], "median", 1),
        "mean_energy": _stat(valid["energy"], "mean", 4),
        "version": str(track_card["version"].iloc[0]),
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }])


# The per-cluster acoustic means the analyst gets — the interpretable subset,
# not all 15 (the label already encodes the distinguishing dims).
_CLUSTER_MEAN_COLS = ("tempo", "energy", "danceability", "brightness", "loudness_db")


def build_cluster_profile(cache: Any, track_card: pd.DataFrame) -> pd.DataFrame:
    """Per-cluster analyst profile from the LATEST song ClusterModel (K2.0).
    Coverage is carried ON the mart (n_assigned vs the corpus n): clusters are
    trained on a snapshot, so the chat can say "39% of your library is
    clustered" instead of silently pretending full coverage. No trained model →
    no mart (absence is honest; the audit treats it as a note)."""
    if track_card is None or track_card.empty:
        return pd.DataFrame()
    from .clusters import latest_model, track_assignments
    model = latest_model(cache, "song")
    if model is None:
        return pd.DataFrame()
    assigns = track_assignments(cache, model.id)
    tc = track_card.set_index("spotify_track_id")
    members: dict[int, list[str]] = {}
    for tid, a in assigns.items():
        if tid in tc.index:                    # ignore assignments for evicted rows
            members.setdefault(int(a["cluster_id"]), []).append(tid)
    n_corpus = int(len(tc))
    rows: list[dict[str, Any]] = []
    for cid_str, label in (model.labels or {}).items():
        cid = int(cid_str)
        m = tc.loc[members.get(cid, [])]
        row: dict[str, Any] = {
            "cluster_id": cid, "label": label,
            "n_assigned": int(len(m)),
            "share_of_corpus": round(len(m) / n_corpus, 4),
            "model_id": int(model.id),
            "silhouette": None if model.silhouette is None
            else round(float(model.silhouette), 3),
        }
        for col in _CLUSTER_MEAN_COLS:
            row[f"mean_{col}"] = None if m.empty else round(float(m[col].mean()), 4)
        rows.append(row)
    rows.sort(key=lambda r: r["cluster_id"])
    return pd.DataFrame(rows)


def build_semantic_marts(cache: Any, perceptual_df: pd.DataFrame,
                         marts_dir: Path) -> dict[str, int]:
    """Write the semantic marts (atomic, idempotent). Called from rebuild_marts
    with the perceptual frame it already computed — no recompute."""
    marts_dir = Path(marts_dir)
    marts_dir.mkdir(parents=True, exist_ok=True)
    fd = feature_dictionary_frame()
    tc = build_track_card(cache, perceptual_df)
    ar = build_artist_rollup(cache, perceptual_df)
    cf = build_corpus_facts(tc, ar)
    cp = build_cluster_profile(cache, tc)
    _write_atomic(fd, marts_dir / "feature_dictionary.parquet")
    if not tc.empty:
        _write_atomic(tc, marts_dir / "track_card.parquet")
    if not ar.empty:
        _write_atomic(ar, marts_dir / "artist_rollup.parquet")
    if not cf.empty:
        _write_atomic(cf, marts_dir / "corpus_facts.parquet")
    if not cp.empty:
        _write_atomic(cp, marts_dir / "cluster_profile.parquet")
    return {"feature_dictionary": len(fd), "track_card": len(tc),
            "artist_rollup": len(ar), "corpus_facts": len(cf),
            "cluster_profile": len(cp)}
