# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v1_17_1_migrations_in_image.py
# @brief      Hotfix v1.17.1 — l'image Docker DOIT embarquer Alembic, et le
#             drift de migrations DOIT être visible dans /health/deep.
#
#             Contexte : l'image v1.17.0 copiait app/ et scripts/ mais ni
#             alembic.ini ni migrations/ → ensure_migrations() échouait en
#             best-effort au boot (CRITICAL loggé, boot continue) → la base
#             prod n'a jamais reçu la révision 0002 → missions.spec_yaml
#             absente → HTTP 500 sur toute la page Missions.
# @license    MIT
# =============================================================================
"""Pins hotfix v1.17.1 (image Docker sans migrations Alembic)."""
from __future__ import annotations

import re
import types
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Pin source-level : le Dockerfile embarque Alembic
# ─────────────────────────────────────────────────────────────────────────


def test_dockerfile_ships_alembic_config_and_migrations() -> None:
    """Sans ces deux COPY, ensure_migrations() ne peut PAS fonctionner en
    prod Docker — et son échec est silencieux par design (best-effort).
    Pin texte : si quelqu'un refactore le Dockerfile et perd ces lignes,
    ce test casse avant la prod. Tolère les flags COPY (--chown=…, ajouté
    pour le layer caching) entre COPY et la source."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    src = dockerfile.read_text()
    assert re.search(r"^COPY\s+(?:--\S+\s+)*alembic\.ini\b", src, re.MULTILINE)
    assert re.search(r"^COPY\s+(?:--\S+\s+)*migrations/", src, re.MULTILINE)


# ─────────────────────────────────────────────────────────────────────────
# migrations_current_sync — détection du drift
# ─────────────────────────────────────────────────────────────────────────


def _fake_settings(monkeypatch, db_path: Path) -> None:
    import app.config as config_mod

    fake = types.SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{db_path}",
    )
    monkeypatch.setattr(config_mod, "get_settings", lambda: fake)


def test_migrations_current_sync_false_without_version_table(
    tmp_path, monkeypatch,
) -> None:
    """Base jamais vue par Alembic (exactement l'état prod v1.17.0 après
    l'échec silencieux) → la sonde doit répondre False, pas exploser."""
    from app.services.alembic_runner import migrations_current_sync

    _fake_settings(monkeypatch, tmp_path / "fresh.db")
    assert migrations_current_sync() is False


def test_migrations_current_sync_true_at_head(tmp_path, monkeypatch) -> None:
    """Round-trip : une base stampée au head courant → True. Le head est
    lu depuis migrations/ (pas hardcodé) pour que le test survive aux
    futures révisions."""
    import sqlalchemy as sa

    from alembic.script import ScriptDirectory

    from app.services.alembic_runner import (
        _alembic_config,
        migrations_current_sync,
    )

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()

    db_path = tmp_path / "at_head.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        ))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": head},
        )
    engine.dispose()

    _fake_settings(monkeypatch, db_path)
    assert migrations_current_sync() is True


def test_migrations_current_sync_false_when_behind_head(
    tmp_path, monkeypatch,
) -> None:
    """Base stampée baseline mais jamais upgradée (le piège d'adoption) →
    False : le monitoring voit le drift au lieu d'attendre le 500."""
    import sqlalchemy as sa

    from app.services.alembic_runner import migrations_current_sync

    db_path = tmp_path / "behind.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        ))
        conn.execute(sa.text(
            "INSERT INTO alembic_version (version_num) VALUES ('0001_baseline')"
        ))
    engine.dispose()

    _fake_settings(monkeypatch, db_path)
    assert migrations_current_sync() is False


# ─────────────────────────────────────────────────────────────────────────
# /health/deep expose le drift
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_deep_degraded_on_migrations_drift(monkeypatch) -> None:
    """db OK + qdrant OK mais migrations en retard → 503 'degraded'.
    C'est LE signal qui manquait en v1.17.0 : tout semblait sain alors
    que la page Missions était morte."""
    import json

    from app.database import init_db
    from app.routers.health import health_check_deep

    await init_db()  # DB de test joignable → db=True

    class _AliveClient:
        def get_collections(self):
            return []

    import app.services.memory_manager as mm
    monkeypatch.setattr(
        mm, "get_memory_manager",
        lambda: types.SimpleNamespace(
            _infra=types.SimpleNamespace(client=_AliveClient())
        ),
    )

    import app.services.alembic_runner as runner
    monkeypatch.setattr(runner, "migrations_current_sync", lambda: False)

    resp = await health_check_deep()
    payload = json.loads(resp.body)

    assert resp.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["db"] is True
    assert payload["qdrant"] is True
    assert payload["migrations"] is False


@pytest.mark.asyncio
async def test_health_deep_ok_when_all_green(monkeypatch) -> None:
    """Chemin nominal : les trois checks verts → 200 'ok'."""
    import json

    from app.database import init_db
    from app.routers.health import health_check_deep

    await init_db()

    class _AliveClient:
        def get_collections(self):
            return []

    import app.services.memory_manager as mm
    monkeypatch.setattr(
        mm, "get_memory_manager",
        lambda: types.SimpleNamespace(
            _infra=types.SimpleNamespace(client=_AliveClient())
        ),
    )

    import app.services.alembic_runner as runner
    monkeypatch.setattr(runner, "migrations_current_sync", lambda: True)

    resp = await health_check_deep()
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert payload["status"] == "ok"
    assert payload["migrations"] is True
