# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_j7b2_wiring.py
# @brief      Sprint 4b V2 J7b.2 — wire promoted python_tool skills into the
#             live bind + dispatch (chat AND mission paths), flag-gated.
# @license    Elastic License 2.0
# =============================================================================
"""J7b.2 wiring tests.

Two shared seams (``append_learned_tools`` at bind time,
``merge_into_tool_map`` at dispatch time) are used by BOTH execution paths:
  - chat:    agent_node (bind)        + tool_node (dispatch)
  - mission: _get_actor_llms (bind)   + dispatch_tool (dispatch)

We pin the seams directly (precise: the learned tool ends up in the list
handed to bind_tools / in the dispatch map, and never shadows a builtin),
then prove it executes live through tool_node (chat) and dispatch_tool
(mission). Everything is a NO-OP unless ``LEARNED_PYTHON_TOOLS_ENABLED`` is
on. Mirrors the fixture pattern of test_learned_tools_runtime.
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


# A pure (computation-only) python_tool — exactly what the V2 generator
# produces today. Compiles + binds + runs end-to-end.
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


class _FakeTool:
    """Stand-in for a built-in registry tool (only ``.name`` is needed)."""

    def __init__(self, name: str) -> None:
        self.name = name


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"j7b2-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"j_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    rt.invalidate(uid)
    yield uid
    rt.invalidate(uid)
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _add_skill(uid, *, content=_VALID, status=SkillStatus.ACTIVE,
                     fmt=SkillContentFormat.PYTHON_TOOL, name="double_it"):
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


def _disable(monkeypatch):
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_ENABLED", raising=False)


# ── BIND seam: append_learned_tools (chat agent_node + mission actor) ─────────


@pytest.mark.asyncio
async def test_append_flag_off_leaves_toolset_unchanged(_user, monkeypatch):
    _disable(monkeypatch)
    await _add_skill(_user)
    base = [_FakeTool("gmail_list_emails")]
    out = await rt.append_learned_tools(base, _user)
    assert [t.name for t in out] == ["gmail_list_emails"]


@pytest.mark.asyncio
async def test_append_flag_on_adds_learned_tool(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    base = [_FakeTool("gmail_list_emails")]
    out = await rt.append_learned_tools(base, _user)
    names = [t.name for t in out]
    assert "gmail_list_emails" in names and "double_it" in names


@pytest.mark.asyncio
async def test_append_never_shadows_a_builtin(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)  # learned tool also named "double_it"
    builtin = _FakeTool("double_it")
    out = await rt.append_learned_tools([builtin], _user)
    # builtin kept, learned NOT duplicated/appended
    assert [t.name for t in out] == ["double_it"]
    assert out[0] is builtin


# ── DISPATCH seam: merge_into_tool_map (chat tool_node + mission dispatch) ────


@pytest.mark.asyncio
async def test_merge_flag_off_is_noop(_user, monkeypatch):
    _disable(monkeypatch)
    await _add_skill(_user)
    tool_map = {"gmail_list_emails": _FakeTool("gmail_list_emails")}
    await rt.merge_into_tool_map(tool_map, _user)
    assert set(tool_map) == {"gmail_list_emails"}


@pytest.mark.asyncio
async def test_merge_flag_on_adds_learned_tool(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    tool_map: dict = {}
    await rt.merge_into_tool_map(tool_map, _user)
    assert "double_it" in tool_map
    assert tool_map["double_it"].invoke({"x": 21}) == 42


@pytest.mark.asyncio
async def test_merge_never_shadows_a_builtin(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    builtin = _FakeTool("double_it")
    tool_map = {"double_it": builtin}
    await rt.merge_into_tool_map(tool_map, _user)
    assert tool_map["double_it"] is builtin


# ── chat DISPATCH end-to-end via tool_node ───────────────────────────────────


async def _run_tool_node(uid, tool_name="double_it", args=None):
    from langchain_core.messages import AIMessage

    from app.agent.tool_node import tool_node

    ai = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {"x": 21}, "id": "tc-1"}],
    )
    out = await tool_node({"messages": [ai], "user_id": uid, "conversation_id": ""})
    msg = out["messages"][0]
    # tool_node uses a dict shape on success (_tool_result) and a ToolMessage
    # object on the not-found path — handle both.
    return msg["content"] if isinstance(msg, dict) else msg.content


@pytest.mark.asyncio
async def test_tool_node_executes_learned_tool_when_enabled(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    content = await _run_tool_node(_user)
    assert "42" in content


@pytest.mark.asyncio
async def test_tool_node_cannot_find_learned_tool_when_disabled(_user, monkeypatch):
    _disable(monkeypatch)
    await _add_skill(_user)
    content = await _run_tool_node(_user)
    assert "42" not in content
    assert "non disponible" in content


# ── mission DISPATCH end-to-end via dispatch_tool ────────────────────────────


@pytest.mark.asyncio
async def test_mission_dispatch_executes_learned_tool_when_enabled(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    from app.agent.missions.nodes import dispatch_tool

    out, ok = await dispatch_tool("double_it", {"x": 21}, "tc-1", _user, mission_id="m-1")
    assert ok is True and "42" in out


@pytest.mark.asyncio
async def test_mission_dispatch_unknown_when_disabled(_user, monkeypatch):
    _disable(monkeypatch)
    await _add_skill(_user)
    from app.agent.missions.nodes import dispatch_tool

    out, ok = await dispatch_tool("double_it", {"x": 21}, "tc-1", _user, mission_id="m-1")
    assert ok is False and "inconnu" in out.lower()


# ── J7c: promote/archive invalidate the per-user runtime cache ───────────────


@pytest.mark.asyncio
async def test_invalidate_helper_fires_for_python_tool(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    # Warm the cache.
    assert len(await rt.load_active_python_tools(_user)) == 1
    # Add a second active tool — invisible until the cache is invalidated.
    await _add_skill(_user, content=_VALID.replace("double_it", "triple_it").replace("x * 2", "x * 3"),
                     name="triple_it")
    assert len(await rt.load_active_python_tools(_user)) == 1  # stale cache

    from app.routers.learning_skills import _invalidate_python_tool_cache

    py = LearnedSkill(
        id="x", user_id=_user, name="n", description="d", content=_VALID,
        content_format=SkillContentFormat.PYTHON_TOOL, status=SkillStatus.ACTIVE,
        source=SkillSource.AUTO_GENERATED,
    )
    _invalidate_python_tool_cache(py)
    assert len(await rt.load_active_python_tools(_user)) == 2  # recompiled


@pytest.mark.asyncio
async def test_invalidate_helper_skips_markdown_playbook(_user, monkeypatch):
    _enable(monkeypatch)
    await _add_skill(_user)
    assert len(await rt.load_active_python_tools(_user)) == 1  # warm
    await _add_skill(_user, content=_VALID.replace("double_it", "triple_it").replace("x * 2", "x * 3"),
                     name="triple_it")

    from app.routers.learning_skills import _invalidate_python_tool_cache

    md = LearnedSkill(
        id="y", user_id=_user, name="n", description="d", content="# playbook",
        content_format=SkillContentFormat.MARKDOWN_PLAYBOOK, status=SkillStatus.ACTIVE,
        source=SkillSource.AUTO_GENERATED,
    )
    _invalidate_python_tool_cache(md)
    # markdown skill → cache NOT busted → still the warm (stale) single tool
    assert len(await rt.load_active_python_tools(_user)) == 1
