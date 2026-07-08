"""
test_backup.py — the D-17 backup/restore drill, synthetic (APP_SPEC Epic E).

The acceptance isn't "a zip exists" — it's that a wiped cache comes back whole
from the backup, spectrograms included, with the previous db kept aside.
"""

from __future__ import annotations

import pytest

from .backup import backup, restore, verify
from .cache import FeatureCache

_F = {"tempo_bpm": 128.0, "rms_mean": 0.2, "spectral_centroid_mean": 2100.0}


@pytest.fixture
def stack(tmp_path):
    """A populated cache + one spectrogram + dirs for backups. The cache engine
    is closed before yielding — the runbook rule is the same: stop the app
    before file-level restore (Windows holds open db files)."""
    db = tmp_path / "data" / "feature_cache.db"
    spec = tmp_path / "data" / "spectrograms"
    spec.mkdir(parents=True)
    cache = FeatureCache(url=f"sqlite:///{db}")
    cache.upsert("t1", _F)
    cache.upsert("t2", dict(_F, tempo_bpm=90.0))
    cache.close()
    (spec / "t1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return {"db": db, "spec": spec, "out": tmp_path / "backups", "url": f"sqlite:///{db}"}


def _rows(url: str, ids: list[str]) -> dict:
    c = FeatureCache(url=url)
    try:
        return c.get(ids)
    finally:
        c.close()


def test_backup_verify_roundtrip(stack):
    zip_path = backup(stack["db"], stack["spec"], stack["out"])
    assert zip_path.exists()
    assert verify(zip_path) == {"tracks": 2, "spectrograms": 1}


def test_restore_drill_recovers_a_wiped_cache(stack):
    zip_path = backup(stack["db"], stack["spec"], stack["out"])

    # Disaster: the live db and spectrograms are destroyed.
    stack["db"].unlink()
    (stack["spec"] / "t1.png").unlink()

    report = restore(zip_path, stack["db"], stack["spec"])
    assert report == {"tracks": 2, "spectrograms": 1}
    got = _rows(stack["url"], ["t1", "t2"])
    assert got.keys() == {"t1", "t2"}                           # rows back
    assert got["t1"]["tempo_bpm"] == 128.0                      # values intact
    assert (stack["spec"] / "t1.png").exists()                  # spectrogram back


def test_restore_keeps_current_db_aside(stack):
    zip_path = backup(stack["db"], stack["spec"], stack["out"])
    diverged = FeatureCache(url=stack["url"])
    diverged.upsert("t3", _F)  # diverge after the backup
    diverged.close()           # "stop the app" before restoring
    restore(zip_path, stack["db"], stack["spec"])
    assert stack["db"].with_suffix(".db.pre-restore").exists()  # safety copy
    assert _rows(stack["url"], ["t3"]) == {}  # restored snapshot predates t3


def test_backup_prunes_to_keep(stack):
    for _ in range(3):
        backup(stack["db"], stack["spec"], stack["out"], keep=2)
    assert len(list(stack["out"].glob("feature_cache_*.zip"))) == 2


def test_backup_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup(tmp_path / "nope.db", tmp_path, tmp_path / "b")