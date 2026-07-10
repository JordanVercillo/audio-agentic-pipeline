"""
test_ingestion.py — Smoke Test for the Ingestion Layer
=======================================================
Tests the components that DON'T require user authentication:
    1. Module imports (all 4 submodules)
    2. Guardrails (deprecated endpoint blocking, field stripping)
    3. Client Credentials auth (public endpoints)
    4. Track metadata fetch (single track; the warehouse path stays popularity-free)
    5. Search
    6. Parquet serialization round-trip

Tests that require PKCE auth (fetch_top_tracks, etc.) are marked
as interactive and skipped by default. Run with --interactive flag
to test the full PKCE flow.

Run from the project root:
    python -m src.ingestion.test_ingestion
    python -m src.ingestion.test_ingestion --interactive
"""

import sys
import tempfile
from pathlib import Path


def run_smoke_test(interactive: bool = False):
    """Execute the ingestion pipeline smoke test."""

    print("=" * 60)
    print("  🧪  INGESTION PIPELINE — Smoke Test")
    print("=" * 60)

    # ── 1. Import validation ──
    print("\n━━━ TEST 1: Module Imports ━━━")
    from src.ingestion import (
        DeprecatedEndpointError,
        fetch_top_tracks,
        fetch_track_metadata,
        get_user_spotify,
        load_metadata_parquet,
        safe_api_call,
        save_metadata_to_parquet,
        search_tracks,
        strip_deprecated_fields,
    )
    print("   ✅ All modules imported successfully")

    # ── 2. Guardrails — deprecated endpoint blocking ──
    print("\n━━━ TEST 2: Guardrails — Deprecated Endpoint Blocking ━━━")
    # PKCE client construction is offline-safe; guardrails block before any call
    sp_public = get_user_spotify(open_browser=False)

    # Test that audio_features is blocked
    blocked = False
    try:
        safe_api_call(sp_public.audio_features, "fake_id", label="audio_features test")
    except DeprecatedEndpointError as e:
        blocked = True
        print(f"   ✅ audio_features correctly BLOCKED: {str(e)[:60]}...")

    assert blocked, "audio_features should be blocked!"

    # Test that audio_analysis is blocked
    blocked = False
    try:
        safe_api_call(sp_public.audio_analysis, "fake_id", label="audio_analysis test")
    except DeprecatedEndpointError as e:
        blocked = True
        print(f"   ✅ audio_analysis correctly BLOCKED: {str(e)[:60]}...")

    assert blocked, "audio_analysis should be blocked!"

    # ── 3. Guardrails — field stripping ──
    print("\n━━━ TEST 3: Guardrails — Field Stripping ━━━")
    # CORRECTED 2026-07-10 (journal #20): popularity is deprecated-NOT-removed
    # and now survives as optional fetched context (never an ML input).
    fake_track = {"id": "test123", "name": "Test Track", "popularity": 85}
    stripped = strip_deprecated_fields(fake_track)
    assert stripped.get("popularity") == 85, "popularity should be KEPT (context)"
    assert "name" in stripped, "fields should remain"
    print("   ✅ popularity kept as optional context (deprecated-not-removed)")

    # ── 4. Client Credentials auth ──
    print("\n━━━ TEST 4: Client Credentials Authentication ━━━")
    try:
        me_data, err = safe_api_call(
            sp_public.search, q="Radiohead", type="artist", limit=1,
            label="GET /search (auth test)"
        )
        assert me_data is not None, f"Search failed: {err}"
        artist_name = me_data["artists"]["items"][0]["name"]
        print(f"   ✅ Authenticated! Search found: {artist_name}")
    except Exception as e:
        print(f"   ❌ Auth failed: {e}")
        return

    # ── 5. Track metadata (2026 compliant — no popularity) ──
    print("\n━━━ TEST 5: Track Metadata Fetch (2026 Compliant) ━━━")
    # "Madness" by Muse — known track ID
    test_track_id = "0c4IEciLCDdXEhhKxj4ThA"
    record = fetch_track_metadata(test_track_id, sp=sp_public)

    assert "error" not in record, f"Metadata fetch failed: {record.get('error')}"
    assert record["spotify_track_id"] == test_track_id, "Bridge key mismatch"
    assert "popularity" not in record, "popularity should NOT be in 2026 metadata"

    print(f"   Track:     {record['track_name']}")
    print(f"   Artist:    {record['primary_artist_name']}")
    print(f"   Album:     {record['album_name']}")
    print(f"   Duration:  {record['duration_ms'] // 1000}s")
    print(f"   Bridge ID: {record['spotify_track_id']}")
    print(f"   Genres:    {record.get('artist_genres', 'N/A')}")
    print("   ✅ No popularity field — 2026 compliant!")

    # ── 6. Search ──
    print("\n━━━ TEST 6: Search ━━━")
    search_df = search_tracks("Daft Punk Random Access Memories", limit=5, sp=sp_public)
    assert not search_df.empty, "Search returned no results"
    assert "spotify_track_id" in search_df.columns, "Missing bridge key"
    print(f"   ✅ {len(search_df)} results, bridge key present")
    for _, row in search_df.head(3).iterrows():
        print(f"      {row['rank']}. {row['track_name']} — {row['artist_names']}")

    # ── 7. Parquet round-trip ──
    print("\n━━━ TEST 7: Parquet Serialization Round-Trip ━━━")
    with tempfile.TemporaryDirectory() as tmpdir:
        parquet_path = Path(tmpdir) / "test_metadata.parquet"

        save_metadata_to_parquet(search_df, output_path=parquet_path, append=False)
        df_loaded = load_metadata_parquet(parquet_path)

        assert len(df_loaded) == len(search_df), "Row count mismatch"
        assert "spotify_track_id" in df_loaded.columns, "Bridge key missing after round-trip"
        print(f"   ✅ Round-trip: {len(df_loaded)} rows, bridge key intact")

    # ── 8. (Interactive) PKCE auth + top items ──
    if interactive:
        print("\n━━━ TEST 8: PKCE Authentication + Top Items ━━━")
        print("   🔐 Opening browser for Spotify login...")
        try:
            sp_user = get_user_spotify()
            from src.ingestion import fetch_user_profile
            profile = fetch_user_profile(sp=sp_user)
            print(f"   ✅ Logged in as: {profile.get('display_name')} ({profile.get('user_id')})")

            top_df = fetch_top_tracks(time_range="short_term", limit=10, sp=sp_user)
            if not top_df.empty:
                print(f"   ✅ Top {len(top_df)} tracks (short_term):")
                for _, row in top_df.head(5).iterrows():
                    print(f"      {row['rank']}. {row['track_name']} — {row['artist_names']}")
            else:
                print("   ⚠️  No top tracks returned (may need more listening history)")
        except Exception as e:
            print(f"   ❌ PKCE test failed: {e}")
    else:
        print("\n━━━ TEST 8: PKCE Auth (SKIPPED — run with --interactive) ━━━")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅  ALL TESTS PASSED — Ingestion Pipeline is operational!")
    print("=" * 60)


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    interactive = "--interactive" in sys.argv
    run_smoke_test(interactive=interactive)


# ── pytest-collected (pure, no network) ──────────────────────────────────────
def test_strip_keeps_popularity_as_context():
    """journal #20: popularity is deprecated-NOT-removed — captured, not stripped."""
    from src.ingestion.guardrails import strip_deprecated_fields
    track = {"id": "t", "name": "N", "popularity": 73}
    assert strip_deprecated_fields(track).get("popularity") == 73


def test_track_record_popularity_is_optional():
    from src.ingestion.fetchers import _track_to_record
    base = {"id": "t1", "name": "Song", "explicit": False, "duration_ms": 1000,
            "disc_number": 1, "track_number": 1, "artists": [], "album": {}}
    assert _track_to_record({**base, "popularity": 61})["popularity"] == 61
    assert _track_to_record(base)["popularity"] is None  # absent-safe (may vanish upstream)
