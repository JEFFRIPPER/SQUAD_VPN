"""Database backups: consistent copies via the SQLite backup API."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path


BACKUP_DIR = Path("data/backups")
PREFIX = "squad_vpn-"
SUFFIX = ".sqlite3.gz"


def list_backups(directory: Path = BACKUP_DIR) -> list[dict[str, object]]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob(f"{PREFIX}*{SUFFIX}"), reverse=True):
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return items


def create_backup(database: Path, directory: Path = BACKUP_DIR, *, keep: int = 7) -> Path:
    """Copy the live database (safe while it is being written) and gzip it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")  # unique even within a second
    raw = directory / f"{PREFIX}{stamp}.sqlite3.part"
    source = sqlite3.connect(database, timeout=30)
    target = sqlite3.connect(raw)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    final = directory / f"{PREFIX}{stamp}{SUFFIX}"
    with open(raw, "rb") as plain, gzip.open(final, "wb", compresslevel=6) as packed:
        shutil.copyfileobj(plain, packed)
    raw.unlink()
    for old in list_backups(directory)[max(1, keep):]:
        (directory / str(old["name"])).unlink(missing_ok=True)
    return final


def backup_due(directory: Path = BACKUP_DIR, *, every_hours: float = 24.0) -> bool:
    backups = list_backups(directory)
    if not backups:
        return True
    newest = Path(directory) / str(backups[0]["name"])
    return time.time() - newest.stat().st_mtime >= every_hours * 3600


def restore_backup(name: str, database: Path, directory: Path = BACKUP_DIR) -> Path:
    """Replace the database with a backup; the current one is kept aside."""
    directory = Path(directory)
    source = directory / Path(name).name  # never outside the backup folder
    if not source.name.startswith(PREFIX) or not source.exists():
        raise FileNotFoundError(f"Нет такой копии: {name}")
    database = Path(database)
    restored = database.with_name(database.name + ".restore")
    with gzip.open(source, "rb") as packed, open(restored, "wb") as plain:
        shutil.copyfileobj(packed, plain)
    check = sqlite3.connect(restored)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Копия повреждена")
    finally:
        check.close()
    if database.exists():
        aside = database.with_name(f"{database.name}.before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        database.replace(aside)
    for suffix in ("-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)
    restored.replace(database)
    return database
