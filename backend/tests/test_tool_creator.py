# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_creator.py
# @brief      Sprint 4b V2 J6c — tests for the generate→validate→persist loop.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app/services/learning/tool_creator.generate_and_persist_tool``.

The generator is mocked (sequence of canned responses) so we exercise
the loop + iteration + persistence without an LLM. The validation chain
runs for real (it's cheap and pure). A real file SQLite is used for the
candidate persistence.
"""
from __future__ import annotations

import json
import textwrap
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import LearnedSkill, SkillContentFormat, SkillStatus
from app.services.learning import tool_creator


VALID = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
).strip()

# parses + passes ast + ruff, but fails mypy (returns int where str declared)
BAD_TYPED = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def double_it(x: int) -> str:
        """Double the integer x."""
        return x * 2
    '''
).strip()


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"tc-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"tc_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


def _patch_generator(monkeypatch, responses):
    """responses: list of (source, info). The fake pops through them and
    records the prior_errors it received each call."""
    state = {"n": 0, "prior_errors": []}

    async def _fake(*, task_description, user_id, prior_errors=None, **_kw):
        # **_kw absorbe les kwargs J7 (profile, allowed_egress,
        # available_secret_labels) sans coupler ces tests au contrat io.
        state["prior_errors"].append(prior_errors)
        idx = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return responses[idx]

    monkeypatch.setattr(tool_creator, "generate_tool_source", _fake)
    return state


_GEN_OK = {"status": "generated", "provider_pick": "deepseek"}


@pytest.mark.asyncio
async def test_creates_candidate_on_first_valid(_user, monkeypatch):
    _patch_generator(monkeypatch, [(VALID, _GEN_OK)])
    result = await tool_creator.generate_and_persist_tool(
        task_description="double a number",
        user_id=_user,
        smoke_kwargs={"x": 21},
        existing_names=set(),
    )
    assert result["status"] == "created"
    assert result["tool_name"] == "double_it"
    assert result["iterations"] == 1

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == result["learned_skill_id"])
        )).scalar_one()
    assert row.content_format == SkillContentFormat.PYTHON_TOOL
    assert row.status == SkillStatus.CANDIDATE
    assert row.content == VALID
    assert json.loads(row.validation_report_json)["ok"] is True


@pytest.mark.asyncio
async def test_iterates_then_succeeds_feeding_errors_back(_user, monkeypatch):
    state = _patch_generator(monkeypatch, [(BAD_TYPED, _GEN_OK), (VALID, _GEN_OK)])
    result = await tool_creator.generate_and_persist_tool(
        task_description="double a number",
        user_id=_user,
        smoke_kwargs={"x": 21},
        existing_names=set(),
        max_iterations=3,
    )
    assert result["status"] == "created"
    assert result["iterations"] == 2
    # first attempt failed at mypy, second created
    assert result["attempts"][0]["validation"].startswith("failed at mypy")
    # the 2nd generation call received the failure as prior_errors
    assert state["prior_errors"][0] is None
    assert state["prior_errors"][1] is not None
    assert "mypy" in state["prior_errors"][1]


@pytest.mark.asyncio
async def test_all_attempts_fail_persists_nothing(_user, monkeypatch):
    # valid code, but the name always collides → registration fails every time
    _patch_generator(monkeypatch, [(VALID, _GEN_OK)])
    result = await tool_creator.generate_and_persist_tool(
        task_description="double a number",
        user_id=_user,
        smoke_kwargs={"x": 21},
        existing_names={"double_it"},
        max_iterations=2,
    )
    assert result["status"] == "validation_failed"
    assert result["iterations"] == 2
    assert all(a["validation"].startswith("failed at registration") for a in result["attempts"])

    async with async_session() as db:
        rows = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.user_id == _user)
        )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_no_provider_stops_immediately(_user, monkeypatch):
    _patch_generator(monkeypatch, [(None, {"status": "no_provider", "error": "no chain"})])
    result = await tool_creator.generate_and_persist_tool(
        task_description="x",
        user_id=_user,
        smoke_kwargs={"x": 1},
        existing_names=set(),
        max_iterations=3,
    )
    assert result["status"] == "no_provider"
    assert result["iterations"] == 1  # no retry on a terminal generator status


@pytest.mark.asyncio
async def test_requires_user_id():
    result = await tool_creator.generate_and_persist_tool(
        task_description="x", user_id="", smoke_kwargs={"x": 1}
    )
    assert result["status"] == "error"
