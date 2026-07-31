

# ── D-70: ISRC + album identity capture (Vision F P4.6.6) ────────────────────
def test_remember_meta_captures_isrc_and_album_identity(tmp_path):
    """The fetcher has always built these four; remember_meta threw them away,
    so the serving cache had an ISRC for 5.6% of the corpus — and ISRC is the
    bridge Phase 5's coverage number depends on."""
    from .cache import FeatureCache
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'd70.db'}")
    c.remember_meta([{"spotify_track_id": "t1", "track_name": "S", "artist_names": "A",
                      "isrc": "USUM71234567", "album_id": "alb1",
                      "album_type": "album", "album_release_date": "2011-05-03"}])
    row = c.all_track_identity()["t1"]
    assert row["isrc"] == "USUM71234567"
    assert row["album_id"] == "alb1" and row["album_type"] == "album"
    assert row["album_release_date"] == "2011-05-03"


def test_remember_meta_never_nulls_a_stored_isrc(tmp_path):
    """Preserve-if-absent, the same posture as popularity: a later fetch that
    omits the field (a playlist item, a partial record) must not erase it."""
    from .cache import FeatureCache
    c = FeatureCache(url=f"sqlite:///{tmp_path / 'd70b.db'}")
    c.remember_meta([{"spotify_track_id": "t1", "track_name": "S", "artist_names": "A",
                      "isrc": "USUM71234567", "album_release_date": "2011"}])
    c.remember_meta([{"spotify_track_id": "t1", "track_name": "S (Remaster)",
                      "artist_names": "A"}])          # no isrc in this one
    ident = c.all_track_identity()["t1"]
    assert ident["isrc"] == "USUM71234567", "a later fetch NULLed a stored ISRC"
    assert ident["album_release_date"] == "2011"
    assert c.all_meta()["t1"]["track_name"] == "S (Remaster)"  # real updates still land
