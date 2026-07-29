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


def broken_extraction_ids(cache) -> set[str]:
    """Analyzed tracks whose DSP output is the broken/silent signature.

    THE one definition, shared by the mart's `feature_valid` gate, the worker's
    post-drain report and the quarantine script — so "broken" cannot come to
    mean three slightly different things (the drift `dedup.py` exists to
    prevent). A failed decode reads tempo 0 and ≈ −180 dBFS; both of the
    extractions Q3 healed looked exactly like this.

    Read-only and cheap (projected columns, no JSON parsed). Reporting is
    deliberately separate from acting: a quarantine DELETES analysis, and that
    stays the owner's call (Q3/D-52)."""
    feats = cache.feature_columns(["tempo_bpm", "rms_mean"])
    out = set()
    for tid, f in feats.items():
        tempo = f.get("tempo_bpm")
        if tempo is not None and tempo <= _MIN_VALID_TEMPO:
            out.add(tid)
    return out

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
        if not paid or m.get("duplicate_of"):
            # O3b: a twin release must not inflate an artist's n_tracks (the
            # analyzed join was already twin-free via the perceptual frame)
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
                       artist_rollup: pd.DataFrame,
                       n_duplicates_flagged: int = 0,
                       n_analyzed_twins: int = 0,
                       n_withheld_unvalidated: int = 0) -> pd.DataFrame:
    """One-row corpus-facts mart (K2.0): the analyst's totals, derived from the
    frames this rebuild already built — no recompute. Acoustic stats run over
    feature_valid rows only, so a dead extraction can't tilt a corpus mean;
    counts report the invalid rows honestly instead of hiding them.
    O3b honesty: the card is twin-free, so n_tracks = UNIQUE recordings; the
    duplicate counts ride along so "N analyzed · M unique" is stateable.
    B2 honesty: source-unvalidated tracks are no longer IN the card, so their
    count rides along too — otherwise the corpus would appear to shrink for no
    stateable reason, and "withheld" would be indistinguishable from "gone"."""
    if track_card is None or track_card.empty:
        return pd.DataFrame()
    valid = track_card[track_card["feature_valid"]]

    def _stat(series: pd.Series, fn: str, ndigits: int) -> float | None:
        return None if valid.empty else round(float(getattr(series, fn)()), ndigits)

    return pd.DataFrame([{
        "n_tracks": int(len(track_card)),
        "n_unique_recordings": int(len(track_card)),   # the card is twin-free (O3b)
        "n_analyzed_incl_duplicates": int(len(track_card)) + int(n_analyzed_twins),
        "n_duplicates_flagged": int(n_duplicates_flagged),
        "n_withheld_unvalidated": int(n_withheld_unvalidated),
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
    # K3: descriptions are written ONCE offline (describe_clusters.py) onto the
    # model row; the mart only projects them — a rebuild never calls an LLM and
    # never loses them. Defensive getattr: pre-K3 DBs read None.
    descs = getattr(model, "descriptions", None) or {}
    rows: list[dict[str, Any]] = []
    for cid_str, label in (model.labels or {}).items():
        cid = int(cid_str)
        m = tc.loc[members.get(cid, [])]
        d = descs.get(cid_str) or {}
        row: dict[str, Any] = {
            "cluster_id": cid, "label": label,
            "n_assigned": int(len(m)),
            "share_of_corpus": round(len(m) / n_corpus, 4),
            "model_id": int(model.id),
            "silhouette": None if model.silhouette is None
            else round(float(model.silhouette), 3),
            "description": str(d.get("text") or ""),
            "description_source": str(d.get("source") or ""),
        }
        for col in _CLUSTER_MEAN_COLS:
            row[f"mean_{col}"] = None if m.empty else round(float(m[col].mean()), 4)
        rows.append(row)
    rows.sort(key=lambda r: r["cluster_id"])
    return pd.DataFrame(rows)


def build_provenance_mart(cache: Any) -> pd.DataFrame:
    """Current acquisition provenance — the LATEST event per bridge key (Q1/D-51):
    where each track's audio came from + the match quality. The analytic table
    the /song provenance section (Q2) and the QA loop (Q4) read. Empty when
    nothing's been extracted-with-provenance yet (honest ∅ — coverage grows as
    new extractions land + the Q3 backfill runs).
    O3b (red-team #1): twins are excluded so prov_keys ⊆ canonical ⊆ track_card
    — a track provenanced first and flagged a twin LATER must not false-fire
    PROVENANCE_ORPHAN. The twin's /song still reads its row via provenance_for
    (a DB read, not this mart)."""
    rows = cache.all_provenance()  # newest-first
    if not rows:
        return pd.DataFrame()
    twins = cache.twin_ids()
    seen: set = set()
    current: list[dict] = []
    for r in rows:  # newest-first → the first sighting of a key IS its latest event
        tid = r.get("spotify_track_id")
        if tid in seen or tid in twins:
            continue
        seen.add(tid)
        current.append({k: v for k, v in r.items() if k != "id"})  # drop the internal event id
    return pd.DataFrame(current)


def build_duplicate_flags_mart(cache: Any) -> pd.DataFrame:
    """The authoritative twin set as a mart (O3b, red-team #8): the audit is
    standalone (stdlib + parquet) and cannot read the serving DB — without this
    it would re-derive dedup from metadata only, which differs from the stored
    cosine-refined flags, and TWIN_LEAKAGE would false-fire or miss."""
    flags = cache.duplicate_flags()
    if not flags:
        return pd.DataFrame()
    return pd.DataFrame(sorted(
        ({"duplicate_id": d, "canonical_id": c} for d, c in flags.items()),
        key=lambda r: r["duplicate_id"]))


def build_dedup_disagreements_mart(cache: Any) -> pd.DataFrame:
    """O4d — pairs the metadata calls one recording and the acoustics refuse.

    Its own mart, NOT extra rows in duplicate_flags: the audit reads
    `set(duplicate_flags["duplicate_id"])` as THE twin set and fires TWIN_LEAKAGE
    for any twin present in track_card. A disagreeing track is not a twin and IS
    in track_card, so smuggling it in there would trip the leakage check that
    protects every canonical population — and the "fix" would be to weaken it.

    Column names deliberately avoid `spotify_track_id` so no bridge-key sweep,
    uniqueness check or leakage loop can mistake this for a canonical
    population (the `duplicate_flags` precedent)."""
    rows = cache.acoustic_disagreements()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(sorted(rows, key=lambda r: (r["track_id_a"], r["track_id_b"])))


def build_semantic_marts(cache: Any, perceptual_df: pd.DataFrame,
                         marts_dir: Path) -> dict[str, int]:
    """Write the semantic marts (atomic, idempotent). Called from rebuild_marts
    with the perceptual frame it already computed — no recompute."""
    marts_dir = Path(marts_dir)
    marts_dir.mkdir(parents=True, exist_ok=True)
    flags = cache.duplicate_flags()
    n_analyzed_twins = len(cache.cached_ids(list(flags))) if flags else 0
    fd = feature_dictionary_frame()
    tc = build_track_card(cache, perceptual_df)
    ar = build_artist_rollup(cache, perceptual_df)
    cf = build_corpus_facts(tc, ar, n_duplicates_flagged=len(flags),
                            n_analyzed_twins=n_analyzed_twins,
                            n_withheld_unvalidated=len(cache.unvalidated_ids()))
    cp = build_cluster_profile(cache, tc)
    pv = build_provenance_mart(cache)
    dfm = build_duplicate_flags_mart(cache)
    dis = build_dedup_disagreements_mart(cache)
    _write_atomic(fd, marts_dir / "feature_dictionary.parquet")
    if not tc.empty:
        _write_atomic(tc, marts_dir / "track_card.parquet")
    if not ar.empty:
        _write_atomic(ar, marts_dir / "artist_rollup.parquet")
    if not cf.empty:
        _write_atomic(cf, marts_dir / "corpus_facts.parquet")
    if not cp.empty:
        _write_atomic(cp, marts_dir / "cluster_profile.parquet")
    if not pv.empty:
        _write_atomic(pv, marts_dir / "track_provenance.parquet")
    if not dfm.empty:
        _write_atomic(dfm, marts_dir / "duplicate_flags.parquet")
    if not dis.empty:
        _write_atomic(dis, marts_dir / "dedup_disagreements.parquet")
    return {"feature_dictionary": len(fd), "track_card": len(tc),
            "artist_rollup": len(ar), "corpus_facts": len(cf),
            "cluster_profile": len(cp), "track_provenance": len(pv),
            "duplicate_flags": len(dfm), "dedup_disagreements": len(dis)}
