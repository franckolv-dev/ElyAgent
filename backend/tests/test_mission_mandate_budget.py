# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate_budget.py
# @brief      Missions autonomes J3 — disjoncteurs D4 : compteurs journaliers,
#             seuils de notification, pause propre + snapshot, reprise.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J3 — pins des disjoncteurs.

Cadrage D4 (arbitrage Franck 11/07) : pas de plafond bloquant — des seuils
de NOTIFICATION (500 actions / 100 appels LLM par jour, surchargeables par
mandat). Franchissement (≥) ⇒ HITL « continuer ? » ; allow ⇒ acquitté pour
la journée ; deny/timeout (30 min) ⇒ pause propre + snapshot + reprise
possible là où la mission s'est arrêtée. Compteurs PERSISTÉS (un restart ne
remet pas le jour à zéro).
"""
from __future__ import annotations

import json as _json
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def _user_j3():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionDailyCounter
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j3_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from sqlalchemy import select
        mids = [r[0] for r in (await db.execute(
            select(Mission.id).where(Mission.user_id == uid))).all()]
        if mids:
            await db.execute(delete(MissionDailyCounter).where(
                MissionDailyCounter.mission_id.in_(mids)))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Compteurs journaliers
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_counters_increment_and_persist(_user_j3):
    from app.services import mission_budget, mission_service

    m = await mission_service.create_mission(user_id=_user_j3, title="c", goal="g")
    c1 = await mission_budget.incr_tool_action(m.id)
    assert (c1.tool_actions, c1.llm_calls) == (1, 0)
    await mission_budget.incr_llm_call(m.id)
    c2 = await mission_budget.incr_tool_action(m.id)
    assert (c2.tool_actions, c2.llm_calls) == (2, 1)
    # lecture indépendante (persisté, pas en mémoire)
    c3 = await mission_budget.get_today(m.id)
    assert (c3.tool_actions, c3.llm_calls) == (2, 1)
    assert c3.day == mission_budget.today_key()
    assert c3.tool_ack is False and c3.llm_ack is False


@pytest.mark.asyncio
async def test_ack_threshold(_user_j3):
    from app.services import mission_budget, mission_service

    m = await mission_service.create_mission(user_id=_user_j3, title="a", goal="g")
    await mission_budget.incr_tool_action(m.id)
    await mission_budget.ack_threshold(m.id, "tool")
    c = await mission_budget.get_today(m.id)
    assert c.tool_ack is True and c.llm_ack is False


@pytest.mark.asyncio
async def test_migration_0019_adds_table_and_column_to_legacy_db(tmp_path, monkeypatch) -> None:
    """Piège d'adoption (pattern 0002/0018) : base existante jamais vue par
    Alembic ⇒ stamp baseline + upgrade doit créer la table compteurs ET la
    colonne snapshot."""
    import sqlite3
    import types

    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, goal TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )

    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    cols = {r[1] for r in check.execute("PRAGMA table_info(missions)")}
    tables = {r[0] for r in check.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check.close()
    assert "autonomy_pause_json" in cols
    assert "mission_daily_counters" in tables
