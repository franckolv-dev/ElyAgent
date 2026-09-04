# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_tache_planifiee_lance_une_mission.py
# @brief      Une tâche planifiée marquée « mission » ne joue pas son prompt
#             en un tour : elle crée et démarre une mission, et ne la
#             double pas tant que la précédente tourne.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""« Nettoyage quotidien Gmail par catégories » (cron 12h30, créée le 25/08)
échoue à chaque tour : « Recursion limit of 60 reached ». Le tri d'une boîte
ne tient pas dans un tour de chat. La mission « Nettoyage mails », elle,
porte carnet, budgets et passages — mais n'est pas récurrente, et son
objectif disait « tous les jours à 12h30 », ce que le juge lui reprochait à
chaque passage.

Le pont : la tâche planifiée donne la récurrence, la mission donne le
travail. ``ScheduledTask.as_mission`` — à l'heure dite, la tâche crée une
mission (objectif = son prompt, source ``scheduled_task``, référence = la
tâche) et la démarre ; le heartbeat fait le reste. Tant que la mission de
la veille tourne encore, la tâche ne la double pas.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db

    await init_db()


async def _utilisateur() -> str:
    from app.database import async_session
    from app.models.user import User

    uid = f"test_pont_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    return uid


async def _tache(uid: str, *, as_mission: bool = True) -> str:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask

    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(ScheduledTask(
            id=tid, user_id=uid, name="Nettoyage quotidien",
            prompt="Trie les mails des six catégories.",
            cron_expression="30 12 * * *", channel="web", as_mission=as_mission,
        ))
        await db.commit()
    return tid


async def _missions_de(tid: str) -> list:
    from app.database import async_session
    from app.models.mission import Mission

    async with async_session() as db:
        return list((await db.execute(
            select(Mission).where(Mission.source_ref == tid)
        )).scalars().all())


async def _tache_relue(tid: str):
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask

    async with async_session() as db:
        return (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == tid)
        )).scalar_one()


def _graphe_interdit(monkeypatch):
    import app.agent.graph as graph_mod

    def _boom():
        raise AssertionError("le graphe plat a été construit pour une tâche « mission »")

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", _boom)


# ── Le pont ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_tache_mission_cree_et_demarre_une_mission(monkeypatch):
    import app.services.scheduler as sched

    _graphe_interdit(monkeypatch)
    uid = await _utilisateur()
    tid = await _tache(uid)

    await sched._execute_task(tid)

    missions = await _missions_de(tid)
    assert len(missions) == 1
    m = missions[0]
    assert m.source == "scheduled_task"
    assert m.goal == "Trie les mails des six catégories."
    assert m.title == "Nettoyage quotidien"
    assert m.status in {"planning", "running"}
    assert m.next_tick_at is not None, "le heartbeat ne la réveillera jamais"

    t = await _tache_relue(tid)
    assert t.last_status == "success"
    assert m.id[:8] in (t.last_result or "")


@pytest.mark.asyncio
async def test_une_mission_encore_en_cours_n_est_pas_doublee(monkeypatch):
    import app.services.scheduler as sched

    _graphe_interdit(monkeypatch)
    uid = await _utilisateur()
    tid = await _tache(uid)
    await sched._execute_task(tid)

    await sched._execute_task(tid)

    assert len(await _missions_de(tid)) == 1
    t = await _tache_relue(tid)
    assert t.last_status == "silent"
    assert "en cours" in (t.last_result or "")


@pytest.mark.asyncio
async def test_une_mission_terminee_laisse_la_suivante_partir(monkeypatch):
    import app.services.scheduler as sched
    from app.services import mission_service

    _graphe_interdit(monkeypatch)
    uid = await _utilisateur()
    tid = await _tache(uid)
    await sched._execute_task(tid)
    premiere = (await _missions_de(tid))[0]
    await mission_service.complete_mission(premiere.id, "Boîte triée.")

    await sched._execute_task(tid)

    assert len(await _missions_de(tid)) == 2


@pytest.mark.asyncio
async def test_une_tache_ordinaire_joue_toujours_le_graphe_plat(monkeypatch):
    """Le pont ne touche pas les tâches existantes."""
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    from langchain_core.messages import AIMessage

    appels = {"n": 0}

    class _Agent:
        async def ainvoke(self, state, config=None):
            appels["n"] += 1
            return {"messages": [AIMessage(content="rapport produit")]}

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _Agent())

    async def _noop(task, content):
        return None

    monkeypatch.setattr(sched, "_deliver_result", _noop)
    uid = await _utilisateur()
    tid = await _tache(uid, as_mission=False)

    await sched._execute_task(tid)

    assert appels["n"] == 1
    assert await _missions_de(tid) == []


# ── L'API porte le drapeau ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_l_api_cree_et_rend_le_drapeau_mission(monkeypatch):
    from app.database import async_session
    from app.models.user import User
    from app.routers import scheduler as sched_router

    monkeypatch.setattr(sched_router, "schedule_task", lambda task: True)
    uid = await _utilisateur()
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.id == uid))).scalar_one()
        cree = await sched_router.create_task(
            sched_router.TaskCreate(
                name="Nettoyage", prompt="Trie.", cron_expression="30 12 * * *",
                as_mission=True,
            ),
            user=user, db=db,
        )
        assert cree.as_mission is True

        modifie = await sched_router.update_task(
            cree.id, sched_router.TaskUpdate(as_mission=False), user=user, db=db,
        )
        assert modifie.as_mission is False


def test_l_outil_de_planification_porte_le_drapeau():
    import inspect

    from app.agent.tools.scheduler_tool import scheduler_create_task

    fn = getattr(scheduler_create_task, "coroutine", None) or getattr(
        scheduler_create_task, "func", scheduler_create_task,
    )
    assert "as_mission" in inspect.signature(fn).parameters
