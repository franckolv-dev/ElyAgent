# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduler_silent_oneshot.py
# @brief      Jalon 2 — [SILENT], one-shot @once, lifecycle tools
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the Jalon-2 scheduler upgrades.

  1. Trigger parsing — ``@once <ISO>`` → DateTrigger, 5-field → CronTrigger.
  2. ``[SILENT]`` — a monitor with nothing new suppresses delivery AND the
     throwaway conversation; a normal result still delivers.
  3. One-shot — a ``@once`` task is auto-deleted after it runs.
  4. Lifecycle tools — ``scheduler_update_task`` / ``scheduler_run_task``.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.database import async_session, init_db
from app.models.conversation import Conversation, Message
from app.models.scheduled_task import ScheduledTask


# ── trigger parsing (pure) ───────────────────────────────────────────────────

def test_parse_oneshot_vs_cron():
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from app.services.scheduler import _parse_cron, _is_oneshot

    assert isinstance(_parse_cron("@once 2026-05-14T08:00"), DateTrigger)
    assert isinstance(_parse_cron("0 8 * * *"), CronTrigger)
    assert _parse_cron("@once not-a-date") is None
    assert _parse_cron("garbage") is None
    assert _is_oneshot("@once 2026-01-01T00:00") is True
    assert _is_oneshot("0 8 * * *") is False
    assert _is_oneshot(None) is False


def test_validate_schedule_expr():
    from app.agent.tools.scheduler_tool import _validate_schedule_expr
    assert _validate_schedule_expr("@once 2026-05-14T08:00") is None
    assert _validate_schedule_expr("0 8 * * *") is None
    assert _validate_schedule_expr("@once nope") is not None
    assert _validate_schedule_expr("99 99 * * *") is not None


# ── fixtures + helpers ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "j2_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"j2_{uid}", email=f"{uid}@test.local",
                    hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(ScheduledTask).where(ScheduledTask.user_id == uid))
        # Delete child messages before conversations — bulk Core delete()
        # doesn't fire the ORM cascade, so we'd hit the FK otherwise.
        conv_ids = (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid)
        )).scalars().all()
        if conv_ids:
            await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(Conversation).where(Conversation.user_id == uid))
        await db.commit()


async def _make_task(uid: str, *, cron: str = "0 8 * * *") -> str:
    async with async_session() as db:
        t = ScheduledTask(user_id=uid, name="Veille test",
                          prompt="surveille X", cron_expression=cron, channel="web")
        db.add(t)
        await db.commit()
        return t.id


class _FakeGraph:
    def __init__(self, content):
        self._content = content

    async def ainvoke(self, _inp, config=None):
        return {"messages": [SimpleNamespace(content=self._content, tool_calls=[])]}


def _patch_execute(monkeypatch, content):
    """Patch _execute_task's heavy dependencies; return a list capturing
    _deliver_result calls."""
    import app.agent.graph as graph_mod
    import app.services.budget_guard as budget_mod
    import app.services.scheduler as sched_mod
    import app.services.learning.outcome_recording as outcome_mod
    import app.services.learning.facade_detection as facade_mod

    delivered: list = []

    async def _fake_budget(_uid):
        return False  # never over budget

    async def _fake_deliver(task, content):
        delivered.append((task.id, content))

    async def _fake_outcome(**_kw):
        return None

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph",
                        lambda: _FakeGraph(content))
    monkeypatch.setattr(budget_mod, "check_user_budget", _fake_budget)
    monkeypatch.setattr(sched_mod, "_deliver_result", _fake_deliver)
    monkeypatch.setattr(outcome_mod, "record_scheduled_outcome", _fake_outcome)
    monkeypatch.setattr(facade_mod, "tools_called_from_messages", lambda _m: [])
    return delivered


async def _task_row(task_id):
    async with async_session() as db:
        return (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )).scalar_one_or_none()


async def _planifie_conv_count(uid):
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.user_id == uid,
                Conversation.title.like("[Planifié]%"),
            )
        )).scalar_one()


# ── [SILENT] ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_silent_suppresses_delivery_and_conversation(_user, monkeypatch):
    from app.services.scheduler import _execute_task
    delivered = _patch_execute(monkeypatch, "[SILENT]")
    tid = await _make_task(_user)

    await _execute_task(tid)

    assert delivered == []                       # no delivery
    t = await _task_row(tid)
    assert t is not None and t.last_status == "silent"   # task kept, marked silent
    assert await _planifie_conv_count(_user) == 0        # throwaway conv removed


@pytest.mark.asyncio
async def test_normal_result_delivers(_user, monkeypatch):
    from app.services.scheduler import _execute_task
    delivered = _patch_execute(monkeypatch, "Voici le résumé du jour.")
    tid = await _make_task(_user)

    await _execute_task(tid)

    assert len(delivered) == 1                   # delivered
    t = await _task_row(tid)
    assert t is not None and t.last_status == "success"
    assert await _planifie_conv_count(_user) == 1        # conversation kept


# ── one-shot auto-delete ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oneshot_autodeleted_after_run(_user, monkeypatch):
    from app.services.scheduler import _execute_task
    _patch_execute(monkeypatch, "Rappel : c'est aujourd'hui.")
    tid = await _make_task(_user, cron="@once 2030-01-01T08:00")

    await _execute_task(tid)

    assert await _task_row(tid) is None          # one-shot removed after run


@pytest.mark.asyncio
async def test_oneshot_silent_also_deleted(_user, monkeypatch):
    from app.services.scheduler import _execute_task
    _patch_execute(monkeypatch, "[SILENT]")
    tid = await _make_task(_user, cron="@once 2030-01-01T08:00")

    await _execute_task(tid)

    assert await _task_row(tid) is None          # finally cleanup runs on silent too


# ── lifecycle tools ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_task_changes_fields_and_pauses(_user, monkeypatch):
    import app.services.scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "schedule_task", lambda _t: True)
    monkeypatch.setattr(sched_mod, "unschedule_task", lambda _id: None)
    from app.agent.tools.scheduler_tool import scheduler_update_task

    tid = await _make_task(_user)
    out = await scheduler_update_task.ainvoke({
        "task_id": tid, "prompt": "nouveau prompt", "enabled": False,
        "user_id": _user,
    })
    assert "pause" in out.lower()
    t = await _task_row(tid)
    assert t.prompt == "nouveau prompt" and t.enabled is False


@pytest.mark.asyncio
async def test_update_task_rejects_bad_cron(_user):
    from app.agent.tools.scheduler_tool import scheduler_update_task
    tid = await _make_task(_user)
    out = await scheduler_update_task.ainvoke({
        "task_id": tid, "cron_expression": "@once nope", "user_id": _user,
    })
    assert "invalide" in out.lower()


@pytest.mark.asyncio
async def test_run_task_spawns(_user, monkeypatch):
    import app.services.background_tasks as bg
    spawned: list = []

    def _fake_spawn(coro, *, label=None):
        spawned.append(label)
        coro.close()  # avoid "coroutine never awaited"
        return None

    monkeypatch.setattr(bg, "spawn", _fake_spawn)
    from app.agent.tools.scheduler_tool import scheduler_run_task

    tid = await _make_task(_user)
    out = await scheduler_run_task.ainvoke({"task_id": tid, "user_id": _user})
    assert "lancée" in out.lower()
    assert spawned and spawned[0] == f"run-now-{tid}"
