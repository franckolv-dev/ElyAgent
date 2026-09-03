# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduler_delete.py
# @brief      Régression 13/06 : supprimer une tâche planifiée doit la retirer
#             RÉELLEMENT de la base (hard delete) + désenregistrer son cron,
#             pas la « masquer ». Plus : ownership (pas de suppression
#             cross-user) et toggle enabled persisté.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de l'endpoint DELETE /scheduler/{id} et du toggle enabled.

Le bug perçu (« je supprime mais la tâche reste et re-tourne à 9h ») venait
de l'ABSENCE d'UI pour les tâches planifiées, pas de l'endpoint — qui fait
bien un hard delete. Ces tests verrouillent ce comportement pour qu'un futur
refactor ne le remplace pas par un soft delete silencieux.

Run with:  cd backend && python -m pytest tests/test_scheduler_delete.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.routers import scheduler as sched_router


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _make_user(db) -> User:
    u = User(
        id=str(uuid.uuid4()),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="x",
    )
    db.add(u)
    await db.flush()
    return u


async def _make_task(db, user_id: str, *, name="Daily") -> ScheduledTask:
    t = ScheduledTask(
        user_id=user_id, name=name, prompt="Envoie mon briefing.",
        cron_expression="0 9 * * *", channel="telegram",
    )
    db.add(t)
    await db.flush()
    return t


@pytest.mark.asyncio
async def test_delete_actually_removes_row_and_unschedules(monkeypatch):
    from app.database import async_session

    unscheduled: list[str] = []
    monkeypatch.setattr(sched_router, "unschedule_task", lambda tid: unscheduled.append(tid))

    async with async_session() as db:
        user = await _make_user(db)
        task = await _make_task(db, user.id)
        task_id = task.id
        await db.commit()

        resp = await sched_router.delete_task(task_id=task_id, user=user, db=db)
        assert "supprimée" in resp["message"]

    # Hard delete : la ligne n'existe PLUS (pas un enabled=False masqué).
    async with async_session() as db:
        still = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )).scalar_one_or_none()
        assert still is None, "la tâche doit être RÉELLEMENT supprimée"
    # Et le cron a été désenregistré (sinon elle re-tournerait quand même).
    assert unscheduled == [task_id]


@pytest.mark.asyncio
async def test_delete_is_404_for_another_users_task(monkeypatch):
    from app.database import async_session

    monkeypatch.setattr(sched_router, "unschedule_task", lambda tid: None)
    async with async_session() as db:
        owner = await _make_user(db)
        intruder = await _make_user(db)
        task = await _make_task(db, owner.id)
        task_id = task.id
        await db.commit()

        with pytest.raises(HTTPException) as err:
            await sched_router.delete_task(task_id=task_id, user=intruder, db=db)
        assert err.value.status_code == 404

    # La tâche du propriétaire est intacte.
    async with async_session() as db:
        still = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )).scalar_one_or_none()
        assert still is not None


@pytest.mark.asyncio
async def test_toggle_enabled_persists_and_unschedules(monkeypatch):
    from app.database import async_session

    scheduled: list[str] = []
    unscheduled: list[str] = []
    monkeypatch.setattr(sched_router, "schedule_task", lambda t: scheduled.append(t.id) or True)
    monkeypatch.setattr(sched_router, "unschedule_task", lambda tid: unscheduled.append(tid))

    async with async_session() as db:
        user = await _make_user(db)
        task = await _make_task(db, user.id)
        task_id = task.id
        await db.commit()

        # Désactivation → enabled False persisté + cron retiré
        body = sched_router.TaskUpdate(enabled=False)
        out = await sched_router.update_task(task_id=task_id, body=body, user=user, db=db)
        assert out.enabled is False
        assert unscheduled == [task_id]

    async with async_session() as db:
        row = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )).scalar_one()
        assert row.enabled is False  # la LIGNE existe encore (désactivée ≠ supprimée)
