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
from typing import Any, Optional

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


def _release_year(raw: Any) -> Optional[int]:
    """Year from a Spotify release_date, or None. Spotify's field is variously
    `2006`, `2006-01`, `2006-01-01`, so only the first four characters are
    dependable — and a remaster reports its REISSUE year, which is why every
    surface built on this says so rather than silently correcting it."""
    try:
        y = int(str(raw)[:4])
    except (TypeError, ValueError):
        return None
    # Recorded music predates 1900 only in ways this corpus will never contain;
    # a stray 0001 or 9999 is a parse artifact, not a release.
    return y if 1900 <= y <= 2100 else None


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
    # ERA. D-70 captured album_release_date for the whole corpus and only
    # /artist read it. Landing them here as DEGENERATE attributes (never a join
    # key — album_id is far too thin to rollup on: 1,532 albums, only 124 with
    # 3+ analyzed tracks) turns a stored column into an answerable question.
    ident = cache.all_track_identity()
    df["release_year"] = df["spotify_track_id"].map(
        lambda t: _release_year((ident.get(t) or {}).get("album_release_date")))
    # NaN-safe, not `y is None`. pandas types a column of ints-and-Nones as
    # float64, which turns every None into NaN — and `NaN is None` is False, so
    # the None check silently passes NaN straight into int() and raises. The
    # column only becomes float when SOME track lacks a release date, so this
    # is a bug that hides until the corpus contains one.
    df["decade"] = df["release_year"].map(
        lambda y: None if y is None or pd.isna(y) else int(y) // 10 * 10)
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



# Below this, a decade's mean is one playlist's worth of taste rather than a
# claim about the era, so the row is dropped instead of drawn.
_MIN_TRACKS_PER_DECADE = 20


def build_era_profile(track_card: pd.DataFrame) -> pd.DataFrame:
    """One row per DECADE — the grain that makes the loudness war visible.

    `loudness_db` and `tempo` are MEASURED (dBFS, BPM); `energy` is a
    corpus-relative rank and is deliberately absent, because a rank cannot say
    anything about an era — it moves when other decades' tracks arrive.

    Only `feature_valid` rows count, and only decades with at least
    `_MIN_TRACKS_PER_DECADE` tracks, so a 3-track 1960s bucket cannot produce a
    headline. `n_tracks` travels with every row so the page can show its own
    denominators.
    """
    if track_card is None or track_card.empty or "decade" not in track_card:
        return pd.DataFrame()
    df = track_card[track_card.get("feature_valid", True) &
                    track_card["decade"].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    df["decade"] = df["decade"].astype(int)
    g = df.groupby("decade")
    out = pd.DataFrame({
        "n_tracks": g.size(),
        "mean_loudness_db": g["loudness_db"].mean().round(2),
        "median_loudness_db": g["loudness_db"].median().round(2),
        "mean_tempo": g["tempo"].mean().round(1),
        "mean_duration_sec": g["duration_sec"].mean().round(1),
        "n_artists": g["artist"].nunique(),
    }).reset_index()
    out = out[out["n_tracks"] >= _MIN_TRACKS_PER_DECADE]
    return out.sort_values("decade").reset_index(drop=True)



# ── fact_section: the corpus's SECOND fact grain ────────────────────────────
# Everything else here is one row per track. This is one row per SECTION of a
# track, which is what lets the warehouse answer questions no track-grain table
# can express — "how often does a song change key partway through?" is not a
# property of a track, it is a property of the relationship between its parts.

_MIN_SECTION_SEC = 1.0          # shorter than this is a detector artifact
_MAX_SECTIONS = 60              # one track fragments to 134; that is not structure


def build_fact_section(cache: Any, canonical: Optional[set] = None) -> pd.DataFrame:
    """One row per (track, section). The bridge key still joins; `section_index`
    only distinguishes rows WITHIN a track.

    Grain: `(spotify_track_id, section_index)`. That pair is a composite row
    identifier, NOT a second ID system — nothing joins on `section_index` alone,
    and the bridge key remains the only key that crosses tables (ground rule 1,
    and the lesson from the track_clusters composite-key bug).

    Twins and source-unvalidated tracks sit out, via the one shared filter every
    other serving surface uses — otherwise a duplicated recording contributes
    its sections twice and `TWIN_LEAKAGE` fires.
    """
    import json

    excluded = set(cache.excluded_from_aggregates())
    if canonical is not None:
        excluded |= (set(cache.all_features()) - set(canonical))
    rows: list[dict[str, Any]] = []
    for tid, blob in cache.all_sections().items():
        if tid in excluded or not blob:
            continue
        try:
            sections = json.loads(blob) if isinstance(blob, str) else blob
        except (TypeError, ValueError):
            continue
        if not isinstance(sections, list) or len(sections) > _MAX_SECTIONS:
            # A 134-section track is the detector fragmenting, not a song with
            # 134 parts. Dropping it whole beats letting it dominate a mean.
            continue
        for i, s in enumerate(sections):
            if not isinstance(s, dict):
                continue
            start, end = s.get("start"), s.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                continue
            dur = float(end) - float(start)
            if dur < _MIN_SECTION_SEC:
                continue
            rows.append({
                "spotify_track_id": tid,
                "section_index": i,
                "start_sec": round(float(start), 2),
                "end_sec": round(float(end), 2),
                "duration_sec": round(dur, 2),
                "label": s.get("label"),
                "tempo_bpm": s.get("tempo_bpm"),
                "loudness_db": s.get("loudness_db"),
                "key": s.get("key"),
                "mode": s.get("mode"),
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["spotify_track_id", "section_index"]).reset_index(drop=True)


def build_section_summary(fact_section: pd.DataFrame) -> pd.DataFrame:
    """Back to track grain — what the section grain lets us SAY about a track.

    This is the payoff of having two grains: `changes_key` cannot be computed
    from a track-grain table at all, because it is a statement about how a
    track's parts differ from each other.
    """
    if fact_section is None or fact_section.empty:
        return pd.DataFrame()
    g = fact_section.groupby("spotify_track_id")
    out = pd.DataFrame({
        "n_sections": g.size(),
        "mean_section_sec": g["duration_sec"].mean().round(2),
        "longest_section_sec": g["duration_sec"].max(),
        "n_distinct_keys": g["key"].nunique(dropna=True),
        "n_distinct_modes": g["mode"].nunique(dropna=True),
        "loudness_range_db": (g["loudness_db"].max() - g["loudness_db"].min()).round(2),
        "tempo_range_bpm": (g["tempo_bpm"].max() - g["tempo_bpm"].min()).round(1),
    }).reset_index()
    out["changes_key"] = out["n_distinct_keys"] > 1
    out["changes_mode"] = out["n_distinct_modes"] > 1
    return out


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
    era = build_era_profile(tc)
    fs = build_fact_section(cache, canonical=set(tc["spotify_track_id"]) if not tc.empty else None)
    ss = build_section_summary(fs)
    _write_atomic(fd, marts_dir / "feature_dictionary.parquet")
    if not tc.empty:
        _write_atomic(tc, marts_dir / "track_card.parquet")
    if not ar.empty:
        _write_atomic(ar, marts_dir / "artist_rollup.parquet")
    if not era.empty:
        _write_atomic(era, marts_dir / "era_profile.parquet")
    if not fs.empty:
        _write_atomic(fs, marts_dir / "fact_section.parquet")
    if not ss.empty:
        _write_atomic(ss, marts_dir / "section_summary.parquet")
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
