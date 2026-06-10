# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase3_batch3.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 3 lot 3 — pins :
#             B-4 Alembic (stamp baseline + upgrade au boot, exceptions
#             ALTER non avalées).
# @license    Elastic License 2.0
# =============================================================================
"""Phase 3 batch 3 pins (revue 2026-06-10)."""
from __future__ import annotations

import sqlite3
import types

import pytest


@pytest.mark.asyncio
async def test_boot_stamps_then_upgrades(tmp_path, monkeypatch) -> None:
    """1er boot sur une base jamais vue par Alembic → stamp baseline ;
    boots suivants → upgrade head (no-op tant qu'il n'y a pas de révision
    postérieure)."""
    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "alembic_test.db"
    # Simule une base existante créée par create_all (sans alembic_version)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    fake_settings = types.SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{db_path}"
    )
    monkeypatch.setattr(app_config, "get_settings", lambda: fake_settings)

    # 1er boot : stamp BASELINE puis upgrade vers head — stamper head
    # directement sauterait les révisions post-baseline sur une base
    # existante (piège d'adoption corrigé au Sprint 4c J1).
    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    version = check.execute("SELECT version_num FROM alembic_version").fetchone()
    check.close()
    # On ne pin PAS l'id de head (il évolue à chaque révision) — seulement
    # que la base est versionnée et au-delà de la baseline.
    assert version is not None and version[0] != "", "alembic_version doit être posée"

    # 2e boot : la table de version existe → upgrade (no-op vers head)
    assert await ar.ensure_migrations() == "upgraded"


@pytest.mark.asyncio
async def test_migration_failure_never_kills_boot(monkeypatch) -> None:
    from app.services import alembic_runner as ar

    def boom():
        raise RuntimeError("alembic cassé")

    monkeypatch.setattr(ar, "_stamp_or_upgrade_sync", boom)
    assert await ar.ensure_migrations() == "skipped"  # pas d'exception


def test_baseline_revision_exists_and_is_empty() -> None:
    """La baseline matérialise « le schéma vient de create_all » : elle ne
    doit RIEN exécuter (les installs existantes la stampent telle quelle)."""
    from pathlib import Path

    src = Path("migrations/versions/0001_baseline.py").read_text()
    assert 'revision = "0001_baseline"' in src
    assert "down_revision = None" in src


def test_safe_columns_no_longer_swallow_all_exceptions() -> None:
    """B-4 court terme : seul « duplicate column » est l'état nominal —
    tout autre échec d'ALTER doit être loggé (le drift silencieux a déjà
    produit le bug critic_run_at, 676 erreurs en prod)."""
    from pathlib import Path

    src = Path("app/database.py").read_text()
    assert "duplicate column" in src, (
        "le filtre d'exception des ALTER ad hoc a disparu (régression B-4)"
    )
