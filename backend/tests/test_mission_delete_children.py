# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_delete_children.py
# @brief      Supprimer une mission doit emporter TOUTES ses tables filles.
#             `mission_daily_counters` n'a pas de ON DELETE CASCADE et
#             n'était pas supprimée explicitement — la suppression rendait
#             un HTTP 500 « FOREIGN KEY constraint failed ».
# @license    Elastic License 2.0
# =============================================================================
"""Suppression d'une mission : aucune ligne fille ne doit rester (28/08/2026).

Cinq tables portent une FK vers `missions`. Quatre déclarent
``ON DELETE CASCADE`` ; `mission_daily_counters` non. Le routeur, lui, ne
supprimait explicitement que `MissionStep` et `MissionPlan` — alors que son
propre commentaire annonce des suppressions explicites « au cas où le CASCADE
ne serait pas déclaré sur toutes les relations ».

Résultat pour l'utilisateur : bouton Supprimer → 500, mission impossible à
retirer de la liste.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission_avec_enfants():
    """Une mission portant une ligne dans CHAQUE table fille."""
    from sqlalchemy import delete, text

    from app.database import async_session, init_db
    from app.models.mission import (
        Mission, MissionDailyCounter, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_del_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="A supprimer", goal="peu importe",
    )
    async with async_session() as db:
        # Les contraintes FK doivent être ACTIVES, sinon le test ne
        # reproduirait rien : SQLite les ignore par défaut.
        await db.execute(text("PRAGMA foreign_keys=ON"))
        db.add(MissionPlan(mission_id=m.id, version=1, plan_text="x", plan_json={}))
        db.add(MissionStep(mission_id=m.id, iteration=1, phase="act"))
        db.add(MissionStepRun(mission_id=m.id, step_id="1", item_index=0,
                              status="done"))
        db.add(MissionDailyCounter(mission_id=m.id, day=date(2026, 8, 28),
                                   tool_actions=1, llm_calls=1))
        await db.commit()
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionDailyCounter, MissionStepRun, MissionStep, MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_supprimer_une_mission_emporte_ses_compteurs(
    mission_avec_enfants, monkeypatch,
) -> None:
    """Le compteur quotidien ne doit plus faire échouer la suppression."""
    from sqlalchemy import func, select, text

    from app.database import async_session
    from app.models.mission import Mission, MissionDailyCounter
    from app.models.user import User
    from app.routers import missions as routeur

    uid, mid = mission_avec_enfants

    async def _fake_own(mission_id, _user):
        async with async_session() as db:
            return await db.get(Mission, mission_id)

    monkeypatch.setattr(routeur, "_own_or_404", _fake_own)

    async with async_session() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))

    # Ne doit pas lever : c'est le 500 « FOREIGN KEY constraint failed ».
    await routeur.delete(mid, current_user=User(id=uid, username="u",
                                                email="u@x", hashed_password="x"))

    async with async_session() as db:
        assert await db.get(Mission, mid) is None, "la mission doit disparaître"
        restants = await db.scalar(
            select(func.count()).select_from(MissionDailyCounter)
            .where(MissionDailyCounter.mission_id == mid)
        )
        assert restants == 0, "les compteurs quotidiens doivent partir avec elle"
