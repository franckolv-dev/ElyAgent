# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learned_tools_runtime.py
# @brief      Sprint 4b V2 J7b — runtime loader for promoted python_tool skills.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for learned_tools_runtime: flag-gated loading + compilation of a
user's active python_tool skills into bindable tools.
"""
from __future__ import annotations

import textwrap
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning import learned_tools_runtime as rt


_VALID = textwrap.dedent(
    '''
    from langchain_core.tools import tool

    from app.skills.base import Domain
    from app.skills.decorator import register


    @register(domain=Domain.WORKSPACE, skill_name="double_it",
              skill_display_name="Double", skill_description="x2",
              skill_icon="x", enabled_by_default=False)
    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
).strip()

# parses + guard-ok but exec fails (undefined module-level name) → skipped
_BROKEN = "from langchain_core.tools import tool\nB = undefined_x\n@tool\ndef f(x: int) -> int:\n    \"\"\"d.\"\"\"\n    return x\n"


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"rt-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"rt_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    rt.invalidate(uid)
    yield uid
    rt.invalidate(uid)
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _add_skill(uid, *, content, status=SkillStatus.ACTIVE, fmt=SkillContentFormat.PYTHON_TOOL,
                     name="double_it"):
    async with async_session() as db:
        db.add(LearnedSkill(
            id=str(uuid.uuid4()), user_id=uid, name=name, description="d",
            content=content, content_format=fmt, status=status,
            source=SkillSource.AUTO_GENERATED,
        ))
        await db.commit()


def _enable(monkeypatch):
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_ENABLED", "1")
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)


# ── flag ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_off_returns_empty(_user, monkeypatch):
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_ENABLED", raising=False)
    await _add_skill(_user, content=_VALID)
    assert await rt.load_active_python_tools(_user) == []


@pytest.mark.asyncio
async def test_kill_switch_wins_over_enabled(_user, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_DISABLED", "1")
    await _add_skill(_user, content=_VALID)
    assert await rt.load_active_python_tools(_user) == []


# ── loading ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loads_and_compiles_active_python_tool(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user, content=_VALID)
    tools = await rt.load_active_python_tools(_user, use_cache=False)
    assert len(tools) == 1
    assert tools[0].name == "double_it"
    assert tools[0].invoke({"x": 21}) == 42


@pytest.mark.asyncio
async def test_broken_skill_is_skipped(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user, content=_BROKEN, name="broken")
    await _add_skill(_user, content=_VALID)
    tools = await rt.load_active_python_tools(_user, use_cache=False)
    assert [t.name for t in tools] == ["double_it"]  # broken one dropped


@pytest.mark.asyncio
async def test_only_active_python_tools(_user, monkeypatch):
    _enable(monkeypatch)
    # a candidate python_tool (not active) and a markdown playbook → both ignored
    await _add_skill(_user, content=_VALID, status=SkillStatus.CANDIDATE, name="cand")
    await _add_skill(_user, content="# a markdown playbook", fmt=SkillContentFormat.MARKDOWN_PLAYBOOK,
                     name="md")
    assert await rt.load_active_python_tools(_user, use_cache=False) == []


# ── cache ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_and_invalidate(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user, content=_VALID)
    first = await rt.load_active_python_tools(_user)
    assert len(first) == 1
    # add another active tool — cached result unchanged until invalidate
    await _add_skill(_user, content=_VALID.replace("double_it", "triple_it").replace("x * 2", "x * 3"),
                     name="triple_it")
    assert len(await rt.load_active_python_tools(_user)) == 1  # still cached
    rt.invalidate(_user)
    assert len(await rt.load_active_python_tools(_user)) == 2  # recompiled
