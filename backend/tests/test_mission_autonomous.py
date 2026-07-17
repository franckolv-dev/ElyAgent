# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_autonomous.py
# @brief      2026-06-04 — autonomous missions auto-approve NON-floor HITL and
#             skip floor tools (NEVER_AUTONOMOUS_TOOLS) without stalling.
# @license    Elastic License 2.0
# =============================================================================
"""Autonomous mode (Franck, 2026-06-04): a scheduled mission running at 3 a.m.
must not stall on a HITL prompt nobody answers. With `autonomous=True`,
non-floor HITL-gated tools are auto-approved; floor tools (irreversible /
external / security) are skipped immediately (step fails, mission continues).
dispatch_tool is imported & executed; registry/hitl faked; a real mission row
carries the autonomous flag (dispatch_tool fetches it).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.agent.missions import nodes as mnodes
from app.database import async_session, init_db
from app.models.mission import Mission
from app.services import mission_service


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def ainvoke(self, args):
        return "EXECUTED"


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = tools

    @property
    def all_tools(self):
        return self._tools


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"auto-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"auto_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    yield uid
    # C3b-2 : un deny du dispatch (via la passerelle) enregistre désormais un
    # signal HitlRefusal (+ failure_case) référençant le user — drainer les
    # tâches de fond puis supprimer les ENFANTS avant le user (FK, flaky CI).
    import asyncio as _aio

    import app.services.background_tasks as bg
    for _ in range(10):
        _tasks = [t for t in list(bg._BG_TASKS) if not t.done()]
        if not _tasks:
            break
        await _aio.gather(*_tasks, return_exceptions=True)
    from app.models.failure_case import FailureCase
    from app.models.hitl_refusal import HitlRefusal
    async with async_session() as db:
        await db.execute(delete(FailureCase).where(FailureCase.user_id == uid))
        await db.execute(delete(HitlRefusal).where(HitlRefusal.user_id == uid))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


def _patch(monkeypatch, tool_name, *, hitl_decision="deny", hitl_raises=False):
    import app.skills as skills_mod
    import app.services.hitl_manager as hm
    import app.services.hitl_descriptions as hd

    monkeypatch.setattr(skills_mod, "get_skill_registry",
                        lambda: _FakeRegistry([_FakeTool(tool_name)]))

    class _FakeHitl:
        async def request_validation(self, description, user_id):  # noqa: ARG002
            if hitl_raises:
                raise AssertionError("HITL prompt should NOT be reached")
            return hitl_decision, None

    monkeypatch.setattr(hm, "get_hitl_manager", lambda: _FakeHitl())

    async def _fake_human(**kwargs):  # noqa: ARG001
        return "desc"

    monkeypatch.setattr(hd, "build_human_hitl_description", _fake_human)


async def _mission(user_id, autonomous: bool) -> str:
    m = await mission_service.create_mission(
        user_id=user_id, title="T", goal="objectif de test autonome", autonomous=autonomous,
    )
    return m.id


# desktop_write_file: ALWAYS_CRITICAL (triggers HITL) but NOT in the floor.
# ssh_execute: ALWAYS_CRITICAL AND in the floor (NEVER_AUTONOMOUS_TOOLS).


@pytest.mark.asyncio
async def test_autonomous_auto_approves_non_floor_tool(_user, monkeypatch):
    mid = await _mission(_user, autonomous=True)
    _patch(monkeypatch, "desktop_write_file", hitl_raises=True)  # HITL must NOT fire
    out, ok = await mnodes.dispatch_tool("desktop_write_file", {"path": "/x", "content": "y"},
                                         "tc1", _user, mission_id=mid)
    assert ok is True
    assert out == "EXECUTED"


@pytest.mark.asyncio
async def test_autonomous_skips_floor_tool_immediately(_user, monkeypatch):
    mid = await _mission(_user, autonomous=True)
    _patch(monkeypatch, "ssh_execute", hitl_raises=True)  # must skip WITHOUT prompting
    out, ok = await mnodes.dispatch_tool("ssh_execute", {"command": "ls"},
                                         "tc1", _user, mission_id=mid)
    assert ok is False
    assert "non exécutée" in out and "autonome" in out


@pytest.mark.asyncio
async def test_non_autonomous_still_prompts(_user, monkeypatch):
    mid = await _mission(_user, autonomous=False)
    _patch(monkeypatch, "desktop_write_file", hitl_decision="deny")
    out, ok = await mnodes.dispatch_tool("desktop_write_file", {"path": "/x", "content": "y"},
                                         "tc1", _user, mission_id=mid)
    assert ok is False
    assert out.startswith("Action refusée")


# ── API surface ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_patch_autonomous(_user):
    from app.routers.missions import MissionUpdate, update_mission

    class _U:
        id = _user

    m = await mission_service.create_mission(
        user_id=_user, title="T", goal="objectif autonome via api", autonomous=True,
    )
    assert m.autonomous is True
    # PATCH can turn it off
    out = await update_mission(m.id, MissionUpdate(autonomous=False), current_user=_U())
    assert out.autonomous is False
