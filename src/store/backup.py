"""
backup.py — the cache is an asset; back it up (APP_SPEC Epic E, D-17).

Every row in the feature cache embodies real extraction time (acquire → DSP →
spectrogram), so "rebuildable" is true but expensive. These functions snapshot
the SQLite cache (WAL-safe, via the sqlite3 backup API — never a raw file copy
of a live WAL database) plus the spectrogram PNGs into one timestamped zip,
verify a backup's contents, and restore — the Epic E acceptance includes an
actual restore drill.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_DB_ARCNAME = "feature_cache.db"
_SPEC_PREFIX = "spectrograms/"


def _snapshot_db(db_path: Path, dest: Path) -> None:
    """WAL-safe point-in-time copy: the backup API blocks mid-transaction states."""
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def backup(db_path: Path, spectrogram_dir: Path, out_dir: Path, *,
           keep: int = 10) -> Path:
    """Create backups/feature_cache_<UTC>.zip; prune to the newest ``keep``."""
    db_path, out_dir = Path(db_path), Path(out_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"no cache db at {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    zip_path = out_dir / f"feature_cache_{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="va_backup_") as tmp:
        snap = Path(tmp) / _DB_ARCNAME
        _snapshot_db(db_path, snap)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, _DB_ARCNAME)
            spec_dir = Path(spectrogram_dir)
            if spec_dir.is_dir():
                for png in sorted(spec_dir.glob("*.png")):
                    zf.write(png, _SPEC_PREFIX + png.name)

    existing = sorted(out_dir.glob("feature_cache_*.zip"))
    for old in existing[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return zip_path


def verify(zip_path: Path) -> dict:
    """Open a backup and report what's inside: {tracks, spectrograms}."""
    with tempfile.TemporaryDirectory(prefix="va_verify_") as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if _DB_ARCNAME not in names:
                raise ValueError(f"{zip_path} has no {_DB_ARCNAME}")
            zf.extract(_DB_ARCNAME, tmp)
            con = sqlite3.connect(Path(tmp) / _DB_ARCNAME)
            try:
                tracks = con.execute("SELECT count(*) FROM track_features").fetchone()[0]
            finally:
                con.close()
    return {"tracks": int(tracks),
            "spectrograms": sum(1 for n in names if n.startswith(_SPEC_PREFIX))}


def restore(zip_path: Path, db_path: Path, spectrogram_dir: Path) -> dict:
    """Restore a backup. The current db (if any) is kept as ``<db>.pre-restore``."""
    db_path, spec_dir = Path(db_path), Path(spectrogram_dir)
    report = verify(zip_path)  # refuse to restore a bad zip before touching anything
    if db_path.exists():
        shutil.copy2(db_path, db_path.with_suffix(db_path.suffix + ".pre-restore"))
        # A stale WAL/SHM pair must not be replayed over the restored snapshot.
        for side in ("-wal", "-shm"):
            Path(str(db_path) + side).unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="va_restore_") as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        shutil.copy2(Path(tmp) / _DB_ARCNAME, db_path)
        src_spec = Path(tmp) / _SPEC_PREFIX.rstrip("/")
        if src_spec.is_dir():
            for png in src_spec.glob("*.png"):
                shutil.copy2(png, spec_dir / png.name)
    return report
