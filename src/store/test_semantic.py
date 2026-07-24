"""
test_semantic.py — the D-49 semantic layer, synthetic. The 4 tripwires guard
the regression CLASSES the design named, not just line coverage (journal #35).
"""

from __future__ import annotations

import pandas as pd
import pytest

from .cache import FeatureCache
from .perceptual import compute_perceptual
from .semantic import (
    build_artist_rollup,
    build_cluster_profile,
    build_corpus_facts,
    build_track_card,
    feature_dictionary_frame,
)
from .test_perceptual import _club, _folk


@pytest.fixture
def corpus(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 's.db'}")
    metas = []
    for i in range(4):
        cache.upsert(f"club{i}", _club(i), time_signature=4)
        cache.upsert(f"folk{i}", _folk(i), time_signature=3)
        metas += [
            {"spotify_track_id": f"club{i}", "track_name": f"Club {i}",
             "artist_names": "DJ Loud", "primary_artist_id": "arLOUD001", "popularity": 60},
            {"spotify_track_id": f"folk{i}", "track_name": f"Folk {i}",
             "artist_names": "Quiet Folk", "primary_artist_id": "arFOLK002", "popularity": 30}]
    # a BROKEN extraction — the exact silent-track shape (tempo 0, loudness ≈ −180)
    broken = {**_folk(0), "tempo_bpm": 0.0, "rms_mean": 1e-9}
    cache.upsert("brokenX", broken, time_signature=4)
    metas.append({"spotify_track_id": "brokenX", "track_name": "Silent",
                  "artist_names": "DJ Loud", "primary_artist_id": "arLOUD001"})
    cache.remember_meta(metas)
    cache.remember_artists([
        {"artist_id": "arLOUD001", "artist_name": "DJ Loud", "genres": "house"},
        {"artist_id": "arFOLK002", "artist_name": "Quiet Folk", "genres": "folk"}])
    return cache


# ── B2: unvalidated features leave the AGGREGATES, not just the display ──────
def test_unvalidated_tracks_leave_every_aggregate(corpus):
    # D-57 withheld these from display while they still shaped the clusters,
    # the percentiles and corpus_facts — numbers we refuse to show a visitor
    # were still deciding the archetype they were shown. Owner call: exclude.
    for i in range(4):
        corpus.remember_provenance(spotify_track_id=f"club{i}",
                                   youtube_url=f"https://y/{i}")
    unvalidated = corpus.unvalidated_ids()
    assert "folk0" in unvalidated and "club0" not in unvalidated

    perc = compute_perceptual(corpus)
    assert set(perc["spotify_track_id"]) == {f"club{i}" for i in range(4)}

    tc = build_track_card(corpus, perc)
    assert set(tc["spotify_track_id"]) == {f"club{i}" for i in range(4)}

    # the withheld count rides along, so "withheld" stays distinguishable from
    # "gone" — a corpus that quietly shrinks is a corpus nobody can audit
    cf = build_corpus_facts(tc, build_artist_rollup(corpus, perc),
                            n_withheld_unvalidated=len(unvalidated)).iloc[0]
    assert cf["n_tracks"] == 4 and cf["n_withheld_unvalidated"] == len(unvalidated)


def test_no_provenance_at_all_excludes_nothing(corpus):
    # THE fail-safe. An empty/unreadable track_provenance table would otherwise
    # mark the whole corpus unvalidated and empty the clusters, /explore and
    # the chat in one rebuild. An exclusion rule must not be able to exclude
    # everything.
    assert corpus.source_validated_ids() == set()
    assert corpus.unvalidated_ids() == set()
    assert corpus.excluded_from_aggregates() == corpus.twin_ids()
    assert not compute_perceptual(corpus).empty


def test_a_repair_returns_a_track_to_the_aggregates(corpus):
    # the queue is drainable: writing provenance is what lets a track back in
    for i in range(4):
        corpus.remember_provenance(spotify_track_id=f"club{i}", youtube_url="u")
    assert "folk1" not in set(compute_perceptual(corpus)["spotify_track_id"])
    corpus.remember_provenance(spotify_track_id="folk1", youtube_url="u")
    assert "folk1" in set(compute_perceptual(corpus)["spotify_track_id"])


# ── the pure dictionary ──────────────────────────────────────────────────────
def test_feature_dictionary_carries_the_rule3_caveat():
    fd = feature_dictionary_frame().set_index("column")
    assert "popularity" in fd.index
    cav = fd.loc["popularity", "caveat"].lower()
    assert "metadata" in cav and "never" in cav and "input" in cav   # rule 3, as a row
    assert fd.loc["tempo", "direction"] == "higher = faster"


# ── tripwire 1: plane coherence (the bug journal #35 is about) ────────────────
def test_tripwire_plane_coherence(corpus):
    perc = compute_perceptual(corpus)
    tc = build_track_card(corpus, perc)
    n_analyzed = len(corpus.all_features())
    assert len(tc) == len(perc) == n_analyzed   # all cache-derived, all agree


# ── tripwire 2: no broken superlative ────────────────────────────────────────
def test_tripwire_no_broken_superlative(corpus):
    tc = build_track_card(corpus, compute_perceptual(corpus)).set_index("spotify_track_id")
    # the silent track survives as a ROW (honesty) but is gated invalid…
    assert tc.loc["brokenX", "feature_valid"] == False  # noqa: E712
    assert (tc[tc["tempo"] <= 1.0]["feature_valid"] == False).all()  # noqa: E712
    # …so "slowest valid song" is a real track, never the 0-bpm dead row
    valid = tc[tc["feature_valid"]]
    assert valid["tempo"].min() > 1.0
    assert pd.isna(tc.loc["brokenX", "tempo_pct"])  # excluded from the percentile rank


# ── tripwire 3: dictionary parity ────────────────────────────────────────────
def test_tripwire_dictionary_parity(corpus):
    fd = feature_dictionary_frame().set_index("column")
    tc = build_track_card(corpus, compute_perceptual(corpus))
    feature_cols = [c for c in tc.columns if c in fd.index]
    assert feature_cols  # some feature columns are documented
    for col in feature_cols:
        assert fd.loc[col, "tier"] and fd.loc[col, "unit"]  # no undocumented feature reaches the analyst


# ── tripwire 4: key resolvability ────────────────────────────────────────────
def test_tripwire_artist_rollup_keys_resolve(corpus):
    ar = build_artist_rollup(corpus, compute_perceptual(corpus))
    meta_ids = {m.get("primary_artist_id") for m in corpus.library_rows()}
    assert not ar.empty
    for paid in ar["primary_artist_id"]:
        assert paid in meta_ids                       # never an orphaned retrieval key
    loud = ar.set_index("primary_artist_id").loc["arLOUD001"]
    assert loud["n_tracks"] == 5 and loud["genres"] == "house"  # 4 club + the broken one


# ── K2.0: corpus_facts ───────────────────────────────────────────────────────
def _semantic_frames(corpus):
    perc = compute_perceptual(corpus)
    tc = build_track_card(corpus, perc)
    ar = build_artist_rollup(corpus, perc)
    return perc, tc, ar


def test_corpus_facts_parity_and_valid_only_stats(corpus):
    _, tc, ar = _semantic_frames(corpus)
    cf = build_corpus_facts(tc, ar).iloc[0]
    assert cf["n_tracks"] == 9 and cf["n_feature_valid"] == 8   # broken row counted, not hidden
    assert cf["n_artists"] == 2
    # acoustic stats over VALID rows only — the −180 dBFS dead row can't tilt them
    valid = tc[tc["feature_valid"]]
    assert cf["median_tempo"] == round(float(valid["tempo"].median()), 1)
    assert cf["median_tempo"] > 1.0
    assert cf["built_at_utc"] and cf["version"] == tc["version"].iloc[0]
    assert build_corpus_facts(pd.DataFrame(), ar).empty          # empty in → no mart


# ── K2.0: cluster_profile ────────────────────────────────────────────────────
def test_cluster_profile_absent_without_a_model(corpus):
    _, tc, _ = _semantic_frames(corpus)
    assert build_cluster_profile(corpus, tc).empty   # no trained model → no mart


def test_cluster_profile_from_a_trained_model(corpus):
    from .clusters import train_song_clusters
    trained = train_song_clusters(corpus)
    assert trained is not None
    _, tc, _ = _semantic_frames(corpus)
    cp = build_cluster_profile(corpus, tc)
    assert len(cp) == trained["k"]
    assert (cp["label"] != "").all()                          # every cluster is named
    assert int(cp["n_assigned"].sum()) <= len(tc)             # never past the corpus
    assert ((cp["share_of_corpus"] >= 0) & (cp["share_of_corpus"] <= 1)).all()
    assert (cp["model_id"] == trained["model_id"]).all()
    # a populated cluster carries real acoustic means
    populated = cp[cp["n_assigned"] > 0]
    assert not populated.empty and populated["mean_tempo"].notna().all()
    # K3d: description columns exist and are empty until the script writes them
    assert (cp["description"] == "").all()
    assert (cp["description_source"] == "").all()


def test_cluster_profile_projects_saved_descriptions(corpus):
    # K3d: descriptions live on the MODEL row (written once, offline); the mart
    # only projects them — a rebuild never loses or regenerates them.
    from .clusters import latest_model, save_descriptions, train_song_clusters
    train_song_clusters(corpus)
    model = latest_model(corpus, "song")
    assert save_descriptions(corpus, model.id, {
        "0": {"text": "Loud and fast tracks.", "source": "llm",
              "prompt_version": "rtcros-cluster-v1"}})
    _, tc, _ = _semantic_frames(corpus)
    cp = build_cluster_profile(corpus, tc).set_index("cluster_id")
    assert cp.loc[0, "description"] == "Loud and fast tracks."
    assert cp.loc[0, "description_source"] == "llm"
    assert cp.loc[1, "description"] == ""                     # unwritten stays empty


# ── K2.0: the audit tripwires (positive AND negative) ────────────────────────
def _write_semantic_marts(tmp_path, corpus, *, drop_card_row=False,
                          wrong_fact=False, bad_share=False, orphan_provenance=False):
    from .clusters import train_song_clusters
    from .perceptual import catalog_frame, compute_feature_stats
    from .semantic import build_provenance_mart
    train_song_clusters(corpus)
    perc, tc, ar = _semantic_frames(corpus)
    cf = build_corpus_facts(tc, ar)
    cp = build_cluster_profile(corpus, tc)
    # a real provenance event for one analyzed track (+ optionally an orphan)
    corpus.remember_provenance(spotify_track_id=tc["spotify_track_id"].iloc[0],
                               youtube_url="u", match_confidence=0.8,
                               matcher_version="heuristic-v1")
    if orphan_provenance:
        corpus.remember_provenance(spotify_track_id="ghost_not_analyzed",
                                   youtube_url="u2", match_confidence=0.5)
    pv = build_provenance_mart(corpus)
    if drop_card_row:
        tc = tc.iloc[1:]                       # a key in perceptual but not the card
    if wrong_fact:
        cf.loc[0, "n_tracks"] = 999
    if bad_share:
        cp.loc[0, "share_of_corpus"] = 1.7
    marts = tmp_path / "marts"
    marts.mkdir()
    perc.to_parquet(marts / "track_perceptual.parquet", index=False)
    catalog_frame().to_parquet(marts / "feature_catalog.parquet", index=False)
    compute_feature_stats(perc).to_parquet(marts / "feature_stats.parquet", index=False)
    tc.to_parquet(marts / "track_card.parquet", index=False)
    ar.to_parquet(marts / "artist_rollup.parquet", index=False)
    cf.to_parquet(marts / "corpus_facts.parquet", index=False)
    cp.to_parquet(marts / "cluster_profile.parquet", index=False)
    pv.to_parquet(marts / "track_provenance.parquet", index=False)
    return marts


def test_provenance_mart_is_current_per_key(corpus):
    # Q1/D-51: append two events for one track → the mart keeps only the latest.
    from .semantic import build_provenance_mart
    corpus.remember_provenance(spotify_track_id="t", youtube_url="old",
                               match_confidence=0.4)
    corpus.remember_provenance(spotify_track_id="t", youtube_url="new",
                               match_confidence=0.9)
    corpus.remember_provenance(spotify_track_id="u", youtube_url="other")
    pv = build_provenance_mart(corpus)
    assert len(pv) == 2 and not pv["spotify_track_id"].duplicated().any()
    row = pv.set_index("spotify_track_id").loc["t"]
    assert row["youtube_url"] == "new" and row["match_confidence"] == 0.9  # latest wins
    assert "id" not in pv.columns                                          # internal id dropped


def _audit():
    from .test_perceptual import _load_audit_module
    return _load_audit_module()


def test_audit_semantic_marts_green_when_coherent(corpus, tmp_path):
    report, _, errors, flags = _audit().check_marts(_write_semantic_marts(tmp_path, corpus))
    # the fixture's broken row trips the (independent, pre-existing)
    # FEATURE_DISTRIBUTION check — the K2.0 flags themselves must read green
    for flag in ("PLANE_COHERENCE", "SEMANTIC_PARITY", "CLUSTER_PROFILE_DRIFT",
                 "PROVENANCE_ORPHAN"):
        assert flags[flag] is False, flag
    assert not errors
    assert report["track_card"]["rows"] == 9 and report["corpus_facts"]["rows"] == 1
    # Q1: provenance mart present, coverage reported (1 real event, no orphan)
    assert "coverage" in report["track_provenance"]


def test_audit_catches_provenance_orphan(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, orphan_provenance=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["PROVENANCE_ORPHAN"] is True
    assert any("non-analyzed" in w for w in warnings)


# ── O3b: the canonical-only plane ────────────────────────────────────────────
def test_corpus_facts_carry_duplicate_honesty(corpus):
    _, tc, ar = _semantic_frames(corpus)
    cf = build_corpus_facts(tc, ar, n_duplicates_flagged=3, n_analyzed_twins=2)
    row = cf.iloc[0]
    assert row["n_unique_recordings"] == row["n_tracks"]
    assert row["n_analyzed_incl_duplicates"] == row["n_tracks"] + 2
    assert row["n_duplicates_flagged"] == 3


def test_duplicate_flags_mart_and_twin_leakage_tripwire(corpus, tmp_path):
    # A flagged twin planted into track_card (simulating filter drift) must
    # trip TWIN_LEAKAGE; the healthy write reads false.
    import pandas as pd
    marts = _write_semantic_marts(tmp_path, corpus)
    pd.DataFrame([{"duplicate_id": "ghost_twin", "canonical_id": "real"}]).to_parquet(
        marts / "duplicate_flags.parquet", index=False)
    _, _, _, flags = _audit().check_marts(marts)
    assert flags["TWIN_LEAKAGE"] is False                  # twin absent everywhere → clean
    tc = pd.read_parquet(marts / "track_card.parquet")
    leak = tc.iloc[[0]].copy()
    leak["spotify_track_id"] = "ghost_twin"
    pd.concat([tc, leak]).to_parquet(marts / "track_card.parquet", index=False)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["TWIN_LEAKAGE"] is True
    assert any("TWIN_LEAKAGE" in w for w in warnings)


def test_provenanced_twin_is_not_an_orphan(corpus, tmp_path):
    # O3b (red-team #1): a track provenanced FIRST and twin-flagged LATER is
    # analyzed, not an orphan — the reference set is track_card ∪ twins.
    import pandas as pd
    marts = _write_semantic_marts(tmp_path, corpus)
    tc = pd.read_parquet(marts / "track_card.parquet")
    twin_id = "late_twin"
    pd.DataFrame([{"duplicate_id": twin_id,
                   "canonical_id": tc["spotify_track_id"].iloc[0]}]).to_parquet(
        marts / "duplicate_flags.parquet", index=False)
    pv = pd.read_parquet(marts / "track_provenance.parquet")
    extra = pv.iloc[[0]].copy()
    extra["spotify_track_id"] = twin_id
    # NOTE: the twin's provenance row rides the MART here only to prove the
    # audit's reference set; build_provenance_mart itself excludes twins.
    pd.concat([pv, extra]).to_parquet(marts / "track_provenance.parquet", index=False)
    _, _, _, flags = _audit().check_marts(marts)
    assert flags["PROVENANCE_ORPHAN"] is False             # twin ≠ orphan


def test_provenance_mart_excludes_twins(corpus):
    from .semantic import build_duplicate_flags_mart, build_provenance_mart
    corpus.remember_provenance(spotify_track_id="k1", youtube_url="u")
    corpus.remember_provenance(spotify_track_id="k2", youtube_url="u2")
    corpus.remember_meta([{"spotify_track_id": t, "track_name": t, "artist_names": "A"}
                          for t in ("k1", "k2")])
    with corpus._Session() as s:
        from .models import TrackMeta
        s.get(TrackMeta, "k2").duplicate_of = "k1"
        s.commit()
    pv = build_provenance_mart(corpus)
    assert "k2" not in set(pv["spotify_track_id"])         # twin excluded (red-team #1)
    dfm = build_duplicate_flags_mart(corpus)
    assert dfm.iloc[0]["duplicate_id"] == "k2" and dfm.iloc[0]["canonical_id"] == "k1"


def test_audit_catches_plane_incoherence(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, drop_card_row=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["PLANE_COHERENCE"] is True
    assert any("PLANE_COHERENCE" in w for w in warnings)


def test_audit_catches_semantic_parity_break(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, wrong_fact=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["SEMANTIC_PARITY"] is True
    assert any("999" in w for w in warnings)


def test_audit_catches_cluster_profile_drift(corpus, tmp_path):
    marts = _write_semantic_marts(tmp_path, corpus, bad_share=True)
    _, warnings, _, flags = _audit().check_marts(marts)
    assert flags["CLUSTER_PROFILE_DRIFT"] is True
    assert any("share_of_corpus" in w for w in warnings)
