# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduler_status.py
# @brief      Feature 13/06 : indicateur d'état des tâches planifiées.
#             _execute_task pose last_status running→success / running→error,
#             et le routeur l'expose. Donne à l'UI un retour visible.
# @license    MIT
# =============================================================================
"""Run with:  cd backend && python -m pytest tests/test_scheduler_status.py -v"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _seed_task() -> tuple[str, str]:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    from app.models.user import User
    uid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[:8]}", email=f"{uid[:8]}@t.local",
                    hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        db.add(ScheduledTask(id=tid, user_id=uid, name="T", prompt="fais X",
                             cron_expression="0 9 * * *", channel="web"))
        await db.commit()
    return uid, tid


async def _status(tid: str) -> tuple[str | None, str | None]:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    async with async_session() as db:
        t = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == tid)
        )).scalar_one()
        return t.last_status, t.last_result


class _FakeAgent:
    def __init__(self, *, raises: bool = False):
        self._raises = raises

    async def ainvoke(self, state, config=None):
        if self._raises:
            raise RuntimeError("boom")
        return {"messages": [AIMessage(content="rapport produit")]}


@pytest.mark.asyncio
async def test_execute_task_marks_success(monkeypatch):
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _FakeAgent())

    async def _noop_deliver(task, content):  # pas de vrai canal en test
        return None
    monkeypatch.setattr(sched, "_deliver_result", _noop_deliver)

    _uid, tid = await _seed_task()
    await sched._execute_task(tid)

    status, result = await _status(tid)
    assert status == "success"
    assert result == "rapport produit"


@pytest.mark.asyncio
async def test_execute_task_marks_error_on_crash(monkeypatch):
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _FakeAgent(raises=True))

    _uid, tid = await _seed_task()
    await sched._execute_task(tid)

    status, result = await _status(tid)
    assert status == "error"
    assert result and result.startswith("Erreur:")


def test_router_response_exposes_status():
    import inspect
    from app.routers.scheduler import TaskResponse
    fields = TaskResponse.model_fields
    assert "last_status" in fields
    assert "last_run_started_at" in fields
    # _to_response doit câbler le champ.
    from app.routers import scheduler as r
    assert "last_status=task.last_status" in inspect.getsource(r._to_response)
