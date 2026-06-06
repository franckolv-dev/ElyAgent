# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_j9_e2e_python_tool.py
# @brief      Sprint 4b V2 J9 — end-to-end integration test of the full
#             auto-developing-agent lifecycle for a PURE python_tool.
# @license    Elastic License 2.0
# =============================================================================
"""J9 — the whole loop, wired together, in one test.

This is the regression net that links the jalons that were each tested in
isolation:
  - J6c  generate → validate (5 stages) → persist a `candidate`
  - J7c  admin promote / archive  → invalidate the per-user runtime cache
  - J7b.2 bind (append_learned_tools) + dispatch (tool_node / dispatch_tool)

We mock ONLY the LLM generator (a canned PURE source) so the run is
deterministic and free — everything downstream runs for real: the
validation pipeline, SQLite persistence, the promote/archive endpoints, the
runtime loader/cache, and live execution through the chat tool_node AND the
mission dispatch_tool.

Crucial assertion: a freshly-generated tool is NOT bound while `candidate`,
becomes bound+dispatchable+executable the moment it's promoted (proving J7c
invalidation actually takes effect against a warmed cache), and disappears
again on archive — and the whole thing is a no-op when the feature flag is
off.
"""
from __future__ import annotations

import textwrap
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillStatus,
)
from app.services.learning import learned_tools_runtime as rt
from app.services.learning import tool_creator


# A PURE (computation-only) tool — what the V2 generator produces today.
# Passes all 5 validation stages (ast/ruff/mypy/smoke/registration).
VALID = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
).strip()

_GEN_OK = {"status": "generated", "provider_pick": "deepseek"}


class _Admin:
    """Stand-in for the require_admin User (endpoints only read `.id`)."""

    def __init__(self, uid: str) -> None:
        self.id = uid


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"j9-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"j9_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    rt.invalidate(uid)
    yield uid
    rt.invalidate(uid)
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


def _enable(monkeypatch):
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_ENABLED", "1")
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)


def _patch_generator(monkeypatch, source):
    async def _fake(*, task_description, user_id, prior_errors=None):  # noqa: ARG001
        return source, _GEN_OK

    monkeypatch.setattr(tool_creator, "generate_tool_source", _fake)


async def _run_tool_node(uid, tool_name="double_it", args=None):
    from langchain_core.messages import AIMessage

    from app.agent.tool_node import tool_node

    ai = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {"x": 21}, "id": "tc-1"}],
    )
    out = await tool_node({"messages": [ai], "user_id": uid, "conversation_id": ""})
    msg = out["messages"][0]
    return msg["content"] if isinstance(msg, dict) else msg.content


@pytest.mark.asyncio
async def test_full_lifecycle_generate_promote_bind_dispatch_archive(_user, monkeypatch):
    _enable(monkeypatch)
    _patch_generator(monkeypatch, VALID)

    from app.routers.learning_skills import archive_skill, promote_skill

    # ── 1. GENERATE → VALIDATE (5 stages, real) → PERSIST candidate ──────────
    result = await tool_creator.generate_and_persist_tool(
        task_description="double a number",
        user_id=_user,
        smoke_kwargs={"x": 21},          # exercises the smoke stage for real
        existing_names=set(),
    )
    assert result["status"] == "created"
    assert result["tool_name"] == "double_it"
    skill_id = result["learned_skill_id"]

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert row.status == SkillStatus.CANDIDATE
    assert row.content_format == SkillContentFormat.PYTHON_TOOL

    # ── 2. WHILE CANDIDATE → not loaded, not bound, not dispatchable ─────────
    #    (and we WARM the cache here, so step 3 must prove invalidation works)
    assert await rt.load_active_python_tools(_user) == []
    assert await rt.append_learned_tools([], _user) == []
    assert "42" not in await _run_tool_node(_user)  # tool_node can't find it

    # ── 3. PROMOTE via the real admin endpoint (J7c invalidates the cache) ───
    admin = _Admin(_user)
    async with async_session() as db:
        out = await promote_skill(skill_id, admin=admin, db=db)
    assert out.status == SkillStatus.ACTIVE

    # ── 4. NOW bound + dispatchable + executable, on BOTH paths ──────────────
    loaded = await rt.load_active_python_tools(_user)
    assert [t.name for t in loaded] == ["double_it"]            # promote → loaded
    bound = await rt.append_learned_tools([], _user)
    assert "double_it" in [t.name for t in bound]              # BIND (chat + mission)

    assert "42" in await _run_tool_node(_user)                 # chat DISPATCH live

    from app.agent.missions.nodes import dispatch_tool
    mission_out, ok = await dispatch_tool("double_it", {"x": 21}, "tc-1", _user, mission_id="m-1")
    assert ok is True and "42" in mission_out                  # mission DISPATCH live

    # ── 5. ARCHIVE via the real endpoint → invalidate → gone again ───────────
    async with async_session() as db:
        archived = await archive_skill(skill_id, admin=admin, db=db)
    assert archived.status == SkillStatus.ARCHIVED
    assert await rt.load_active_python_tools(_user) == []      # no longer active
    assert "42" not in await _run_tool_node(_user)


@pytest.mark.asyncio
async def test_flag_off_promoted_tool_is_inert_everywhere(_user, monkeypatch):
    """Even a PROMOTED (active) python_tool is invisible while the master
    flag is off — the kill-switch / disabled-by-default guarantee."""
    _enable(monkeypatch)
    _patch_generator(monkeypatch, VALID)

    from app.routers.learning_skills import promote_skill

    result = await tool_creator.generate_and_persist_tool(
        task_description="double a number",
        user_id=_user,
        smoke_kwargs={"x": 21},
        existing_names=set(),
    )
    admin = _Admin(_user)
    async with async_session() as db:
        await promote_skill(result["learned_skill_id"], admin=admin, db=db)
    assert len(await rt.load_active_python_tools(_user)) == 1   # active + flag on

    # Flip the flag off — load returns [] before it even touches the cache.
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_ENABLED", raising=False)
    assert await rt.load_active_python_tools(_user) == []
    assert await rt.append_learned_tools([], _user) == []
    assert "42" not in await _run_tool_node(_user)
