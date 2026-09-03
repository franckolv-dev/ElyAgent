# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase2_batch1.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 2 lot 1 — pins :
#             B-2 (pragmas connexions FTS hors-engine), backup SQLite
#             nocturne, B-9 (quota + purge uploads).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Phase 2 batch 1 pins (revue 2026-06-10)."""
from __future__ import annotations

import os
import time

import pytest


# ─────────────────────────────────────────────────────────────────────────
# B-2 — connexions hors-engine : mêmes pragmas que l'engine
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlite_aio_connect_applies_engine_pragmas(tmp_path) -> None:
    """Avant B-2 les stores FTS ouvraient aiosqlite avec les défauts
    sqlite3 : 5 s de lock timeout (vs 30 s engine) et synchronous=FULL.
    Sous écrivains concurrents : « database is locked » silencieux →
    ligne d'index FTS perdue définitivement."""
    from app.services.sqlite_aio import connect

    db_path = str(tmp_path / "pragmas.db")
    async with connect(db_path) as db:
        cur = await db.execute("PRAGMA busy_timeout")
        busy = (await cur.fetchone())[0]
        cur = await db.execute("PRAGMA synchronous")
        sync = (await cur.fetchone())[0]

    assert busy == 30_000, f"busy_timeout={busy} — doit refléter l'engine (30000)"
    assert sync == 1, f"synchronous={sync} — doit être NORMAL (1), pas FULL (2)"


def test_fts_stores_use_gated_connect() -> None:
    """Les 11 sites de connexion des deux stores FTS doivent passer par
    le helper — un retour à aiosqlite.connect() nu réintroduit B-2."""
    from pathlib import Path

    for mod in ("fts_store", "messages_fts_store"):
        src = Path(f"app/services/{mod}.py").read_text()
        assert "aiosqlite.connect(" not in src.replace(
            "# aiosqlite.connect(", ""
        ), f"{mod}.py ouvre encore une connexion aiosqlite nue (régression B-2)"
        assert "from app.services.sqlite_aio import connect" in src


# ─────────────────────────────────────────────────────────────────────────
# Backup SQLite nocturne (§4 — Qdrant était sauvegardé, la DB jamais)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlite_backup_creates_consistent_copy(tmp_path, monkeypatch) -> None:
    import sqlite3
    import types

    from app.services import sqlite_backup as sb

    src_db = tmp_path / "cyberentity.db"
    conn = sqlite3.connect(src_db)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.execute("INSERT INTO t VALUES ('donnée')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        sb, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{src_db}"),
    )

    created = await sb.run_backup()

    assert len(created) == 1
    backup = created[0]
    assert os.path.exists(backup)
    # La copie est une base SQLite valide et complète
    check = sqlite3.connect(backup)
    assert check.execute("SELECT x FROM t").fetchone() == ("donnée",)
    check.close()


@pytest.mark.asyncio
async def test_sqlite_backup_rotation_removes_old_files(tmp_path, monkeypatch) -> None:
    import sqlite3
    import types

    from app.services import sqlite_backup as sb

    src_db = tmp_path / "cyberentity.db"
    conn = sqlite3.connect(src_db)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups" / "sqlite"
    backup_dir.mkdir(parents=True)
    stale = backup_dir / "cyberentity-20200101-000000.db"
    stale.write_bytes(b"old")
    old = time.time() - 30 * 86400
    os.utime(stale, (old, old))

    monkeypatch.setattr(
        sb, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{src_db}"),
    )
    monkeypatch.setenv("ELY_SQLITE_BACKUP_RETENTION_DAYS", "7")

    created = await sb.run_backup()

    assert created, "le backup du jour doit être créé"
    assert not stale.exists(), "le backup de 30 jours doit être tourné"


# ─────────────────────────────────────────────────────────────────────────
# B-9 — quota par user + purge des vieux uploads
# ─────────────────────────────────────────────────────────────────────────


def test_upload_quota_rejects_when_exceeded(tmp_path, monkeypatch) -> None:
    from fastapi import HTTPException

    from app.routers import upload as up

    user_dir = tmp_path / "u1"
    user_dir.mkdir()
    (user_dir / "gros.bin").write_bytes(b"x" * (1024 * 1024))  # 1 Mo utilisés

    monkeypatch.setattr(up, "UPLOAD_QUOTA_MB", 1)
    with pytest.raises(HTTPException) as exc_info:
        up._check_user_quota(user_dir, incoming_size=200_000)
    assert exc_info.value.status_code == 413

    # Sous le quota : passe sans lever
    monkeypatch.setattr(up, "UPLOAD_QUOTA_MB", 10)
    up._check_user_quota(user_dir, incoming_size=200_000)

    # Quota désactivé : passe toujours
    monkeypatch.setattr(up, "UPLOAD_QUOTA_MB", 0)
    up._check_user_quota(user_dir, incoming_size=10**12)


@pytest.mark.asyncio
async def test_purge_old_uploads_keeps_recent_files(tmp_path, monkeypatch) -> None:
    from app.routers import upload as up

    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(up, "UPLOADS_RETENTION_DAYS", 90)

    user_dir = tmp_path / "u1"
    user_dir.mkdir()
    fresh = user_dir / "recent.png"
    fresh.write_bytes(b"new")
    stale = user_dir / "vieux.png"
    stale.write_bytes(b"old")
    old = time.time() - 120 * 86400
    os.utime(stale, (old, old))

    removed = await up.purge_old_uploads()

    assert removed == 1
    assert fresh.exists(), "un fichier récent ne doit JAMAIS être purgé"
    assert not stale.exists()


@pytest.mark.asyncio
async def test_purge_disabled_when_retention_zero(tmp_path, monkeypatch) -> None:
    from app.routers import upload as up

    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(up, "UPLOADS_RETENTION_DAYS", 0)

    stale = tmp_path / "u1"
    stale.mkdir()
    f = stale / "vieux.png"
    f.write_bytes(b"old")
    very_old = time.time() - 365 * 86400
    os.utime(f, (very_old, very_old))

    assert await up.purge_old_uploads() == 0
    assert f.exists()
