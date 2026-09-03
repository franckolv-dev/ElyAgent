# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/sqlite_backup.py
# @brief      Backup nocturne des bases SQLite via VACUUM INTO + rotation
#             (revue multi-utilisateurs 2026-06-10, §4 — Qdrant était
#             sauvegardé chaque nuit, la VRAIE source de vérité jamais).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Nightly SQLite backups.

``cyberentity.db`` holds users, conversations, missions, learning signals —
the single source of truth — yet only Qdrant had a nightly backup job. A
WAL-interrupted write (power cut, disk full from unbounded uploads) means
losing everything.

``VACUUM INTO`` is the safe way to snapshot a live SQLite database: it
takes a read transaction (writers keep working, WAL) and produces a
compacted, consistent copy. The missions checkpointer file is included
when present.

Backups land in ``<db_dir>/backups/sqlite/`` — already covered by the
Docker volume mount (``./data/db:/app/data``), so they persist on the
host. Rotation keeps ``ELY_SQLITE_BACKUP_RETENTION_DAYS`` (default 7).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)


def _db_files() -> list[Path]:
    url = get_settings().database_url
    if "sqlite" not in url:
        return []  # Postgres : le backup relève de pg_dump, pas d'ici
    main_db = Path(url.split("sqlite+aiosqlite:///")[-1])
    files = [main_db]
    missions = main_db.parent / "missions_checkpoints.sqlite"
    if missions.exists():
        files.append(missions)
    return [f for f in files if f.exists()]


async def run_backup() -> list[str]:
    """Snapshot every SQLite DB, then rotate old backups. Returns paths."""
    files = _db_files()
    if not files:
        logger.debug("sqlite backup: no sqlite database to back up")
        return []

    backup_dir = files[0].parent / "backups" / "sqlite"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    created: list[str] = []
    for src in files:
        dest = backup_dir / f"{src.stem}-{stamp}{src.suffix or '.db'}"
        try:
            async with aiosqlite.connect(str(src), timeout=30) as db:
                # Les curseurs doivent être FERMÉS avant le VACUUM, sinon
                # sqlite refuse (« SQL statements in progress »).
                await (await db.execute("PRAGMA busy_timeout=30000")).close()
                # VACUUM INTO exige que la cible n'existe pas — garanti par
                # le timestamp. Quote-safe (un chemin peut contenir ') :
                escaped = str(dest).replace("'", "''")
                await (await db.execute(f"VACUUM INTO '{escaped}'")).close()
            created.append(str(dest))
            logger.info("sqlite backup: %s → %s", src.name, dest)
        except Exception as exc:
            logger.warning("sqlite backup failed for %s: %s", src, exc)

    _rotate(backup_dir)
    return created


def _rotate(backup_dir: Path) -> int:
    days = int(os.environ.get("ELY_SQLITE_BACKUP_RETENTION_DAYS", "7"))
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for f in backup_dir.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("sqlite backup rotation: %d ancien(s) backup(s) supprimés", removed)
    return removed
