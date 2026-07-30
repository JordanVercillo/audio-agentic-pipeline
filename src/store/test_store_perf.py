"""
test_store_perf.py — speed guards that assert WORK DONE, not milliseconds.

A millisecond threshold in CI measures a runner's noisy neighbour. But the
deeper reason to avoid one is that the regression being guarded here is a SHAPE
regression, not a speed regression: someone writes `select(TrackFeatures)` on a
request path, or drops `analyzed_ids()` back to `set(all_features())`. That is a
categorical fault, so a categorical assertion catches it deterministically on a
handful of synthetic tracks — where a timing assertion would need a real corpus
to show any signal at all.

Measured cost of the faults these guard (live corpus, 2026-07-25):
  library_rows      99 ms  → 9 ms   (6.6 MB of JSON parsed for 18 KB of floats)
  analyzed_ids      88 ms  → 0.7 ms (parsed every value, kept only the keys)
  similar()        176 ms  → ~2 ms  (rebuilt the corpus z-stats per page view)

Synthetic only — no API, no audio, no real corpus.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from .cache import _SIMILARITY_COLS, FeatureCache

_BASE = {"tempo_bpm": 120.0, "rms_mean": 0.2, "spectral_centroid_mean": 2000.0,
         "spectral_rolloff_mean": 4000.0, "zcr_mean": 0.05, "harmonic_ratio": 0.5,
         "onset_strength_mean": 1.2, "spectral_bandwidth_mean": 1500.0,
         **{f"mfcc_mean_{i}": float(i) for i in range(5)}}

# The columns whose presence in a request-path query IS the regression: the
# 82-col contract dict and the three large display arrays.
_HEAVY = ("track_features.features", "track_features.loudness_curve",
          "track_features.beat_times", "track_features.sections")


def _features(i: int) -> dict:
    return {**_BASE, "tempo_bpm": 100.0 + i, "rms_mean": 0.1 + i / 100.0}


@pytest.fixture
def corpus(tmp_path):
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'perf.db'}")
    for i in range(12):
        tid = f"trk{i:02d}"
        c.upsert(tid, _features(i), spectrogram_uri=f"{tid}.png")
        # display JSON that must never be dragged onto a request path
        c.set_loudness_curve(tid, [float(x) for x in range(120)])
        c.set_beat_times(tid, [x * 0.5 for x in range(400)])
        c.set_sections(tid, [{"start": 0, "end": 10, "label": "A"}])
        c.remember_provenance(spotify_track_id=tid, youtube_url=f"https://y/{tid}",
                              match_confidence=0.9)
    c.remember_meta([{"spotify_track_id": f"trk{i:02d}", "track_name": f"S{i}",
                      "artist_names": "Band", "duration_ms": 200000}
                     for i in range(12)])
    return c


def _sql_log(cache) -> list[str]:
    """Capture every statement a block of code executes, as compiled SQL."""
    stmts: list[str] = []
    event.listen(cache.engine, "before_cursor_execute",
                 lambda conn, cur, s, p, ctx, many: stmts.append(s))
    return stmts


# ── G1: the shape tripwire ───────────────────────────────────────────────────
def test_library_rows_never_reads_the_heavy_json_columns(corpus):
    """A catalog row needs three floats. `select(TrackFeatures)` drags in the
    82-column dict plus three large JSON arrays — one such line and /library is
    an order of magnitude slower with no test failing."""
    stmts = _sql_log(corpus)
    corpus.library_rows()
    assert stmts, "no SQL captured — the listener isn't wired"
    for s in stmts:
        for heavy in _HEAVY:
            assert heavy not in s, f"library_rows re-read {heavy}:\n{s}"


def test_analyzed_ids_reads_ids_only(corpus):
    stmts = _sql_log(corpus)
    corpus.analyzed_ids()
    assert len(stmts) == 1
    for heavy in _HEAVY:
        assert heavy not in stmts[0]


def test_analytics_population_never_reads_the_heavy_json_columns(corpus):
    """/analytics and /artist z-score a NAMED subset of the feature dict against
    the corpus. Both called `all_features()` until Vision F P4.6.2 — measured
    1,092 ms / 21 MB vs 54 ms / 1.4 MB projected, per request, growing linearly
    with the corpus. The projection is the fix; this is the tripwire that keeps
    it (the same fault the /library guard above catches, on the two routes that
    guard never covered)."""
    from ..webapp.analytics import _SIGNATURE_DIMS

    for cols in ([c for c, *_ in _SIGNATURE_DIMS], _SIMILARITY_COLS):
        stmts = _sql_log(corpus)
        got = corpus.feature_columns(cols)
        assert got, "no rows projected — the fixture or the projection broke"
        for s in stmts:
            for heavy in _HEAVY[1:]:
                assert heavy not in s, f"population read {heavy}:\n{s}"
        # `features` IS touched (the columns live inside it) but only via a
        # per-column extract — never as the whole-dict column.
        assert not any("track_features.features " in s or
                       s.rstrip().endswith("track_features.features")
                       for s in stmts), "the whole 82-col dict was selected"


def test_similar_never_reads_the_display_json_columns(corpus):
    """`features` IS read (the similarity columns live inside it) but PROJECTED;
    the curve, beat grid and sections must never be."""
    stmts = _sql_log(corpus)
    corpus.similar("trk00", k=3)
    for s in stmts:
        for heavy in _HEAVY[1:]:
            assert heavy not in s, f"similar() re-read {heavy}:\n{s}"


# ── G2: the amortization invariant ───────────────────────────────────────────
def test_similarity_plane_is_built_once_per_population(corpus):
    """The warm path must do no O(corpus) work: many calls, one build."""
    before = corpus._plane_builds
    for tid in [f"trk{i:02d}" for i in range(12)] * 4:
        corpus.similar(tid, k=3)
    assert corpus._plane_builds - before == 1


# ── G3: the staleness tripwires — one per invalidation edge ──────────────────
def test_similar_reflects_a_new_extraction_immediately(corpus):
    """Bug A5 was a persisted derived plane that a repair updated the source of
    without refreshing. This makes the /song version impossible: no rebuild
    hook, no restart, no mart refresh in between."""
    corpus.similar("trk00", k=3)                       # warm the plane
    corpus.upsert("twinish", {**_features(0), "tempo_bpm": 100.05})
    corpus.remember_meta([{"spotify_track_id": "twinish", "track_name": "Near",
                           "artist_names": "Other"}])
    corpus.remember_provenance(spotify_track_id="twinish", youtube_url="https://y/n")
    assert "twinish" in [t for t, _ in corpus.similar("trk00", k=3)]


def test_similar_reflects_a_quarantine_immediately(corpus):
    top = corpus.similar("trk00", k=3)[0][0]
    corpus.quarantine_tracks({top: "wrong take"})
    assert top not in [t for t, _ in corpus.similar("trk00", k=3)]


def test_similar_reflects_a_twin_flag_immediately(corpus):
    top = corpus.similar("trk00", k=3)[0][0]
    from .models import TrackMeta
    with corpus._Session() as s:
        s.get(TrackMeta, top).duplicate_of = "trk01"
        s.commit()
    assert top not in [t for t, _ in corpus.similar("trk00", k=3)]


def test_similar_reflects_a_repair_validating_a_track(corpus):
    """An unvalidated track is excluded; writing provenance re-admits it, and
    the visitor must see that on the next request."""
    corpus.upsert("unval", {**_features(0), "tempo_bpm": 100.02})
    corpus.remember_meta([{"spotify_track_id": "unval", "track_name": "U",
                           "artist_names": "Other"}])
    assert "unval" not in [t for t, _ in corpus.similar("trk00", k=3)]
    corpus.remember_provenance(spotify_track_id="unval", youtube_url="https://y/u",
                               match_confidence=0.9)
    assert "unval" in [t for t, _ in corpus.similar("trk00", k=3)]


def test_a_display_only_backfill_does_not_invalidate_the_plane(corpus):
    """The token is biased toward over-invalidation, but not blindly: writing a
    loudness curve touches no similarity column and must not force a rebuild."""
    corpus.similar("trk00", k=3)
    before = corpus._plane_builds
    corpus.set_loudness_curve("trk05", [1.0, 2.0, 3.0])
    corpus.similar("trk00", k=3)
    assert corpus._plane_builds == before


# ── G4: query count is constant in corpus size ───────────────────────────────
@pytest.mark.parametrize("n", [5, 40])
def test_similar_query_count_does_not_grow_with_the_corpus(tmp_path, n):
    """Not "fast" — CONSTANT. A per-row read inside a loop is invisible at 12
    tracks and fatal at 12,000."""
    c = FeatureCache(url=f"sqlite:///{tmp_path / f'q{n}.db'}")
    for i in range(n):
        c.upsert(f"t{i:03d}", _features(i))
        c.remember_provenance(spotify_track_id=f"t{i:03d}", youtube_url="https://y/x")
    c.remember_meta([{"spotify_track_id": f"t{i:03d}", "track_name": f"S{i}",
                      "artist_names": "B"} for i in range(n)])
    stmts = _sql_log(c)
    c.similar("t000", k=6)
    assert len(stmts) <= 6, f"{len(stmts)} queries for one similar() call"


# ── G5: equivalence lock ─────────────────────────────────────────────────────
def test_similar_ranks_by_distance_and_excludes_itself(corpus):
    """Protects the refactor itself: the metric and the ordering are the
    contract, not an implementation detail of how the plane is built."""
    out = corpus.similar("trk00", k=5)
    assert "trk00" not in [t for t, _ in out]
    assert [d for _, d in out] == sorted(d for _, d in out)
    # trk01 differs from trk00 by one step in every dimension — nearest by design
    assert out[0][0] == "trk01"
    assert corpus.similar("nope", k=3) == []          # unknown id, never raises
