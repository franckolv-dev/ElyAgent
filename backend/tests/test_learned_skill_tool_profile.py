# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learned_skill_tool_profile.py
# @brief      Sprint 4b V3 J6.a — `LearnedSkill.tool_profile` column + enum.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins three things — once they hold, every later J6 sub-PR can rely on them:

  1. The constant set is exactly {"pure", "io"} (no typos in any caller).
  2. A new LearnedSkill defaults to ``tool_profile == "pure"`` when no
     value is passed — every existing call-site that doesn't know about
     the field keeps its V2 behaviour.
  3. The column persists round-trip (DEFAULT on the ALTER TABLE + the
     SQLAlchemy default agree).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
    SkillToolProfile,
)


# ── Pure (no DB) checks ─────────────────────────────────────────────────────


def test_skilltoolprofile_constants_are_canonical():
    """Pin: only two profiles — pure (V2) and io (V3). Any new profile (eg.
    a hypothetical `io_extended` in V3.x) must add a constant here AND
    extend SkillToolProfile.ALL — both gates so adding one without the
    other fails this test."""
    assert SkillToolProfile.PURE == "pure"
    assert SkillToolProfile.IO == "io"
    assert SkillToolProfile.ALL == {"pure", "io"}


# ── DB roundtrip ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def _seeded_user_for_tool_profile():
    await init_db()
    from app.models.user import User
    user_id = "tool_profile_user"
    async with async_session() as db:
        existing = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id=user_id,
                username="tool_profile_test_user",
                email=f"{user_id}@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(
            delete(LearnedSkill).where(LearnedSkill.user_id == user_id)
        )
        await db.commit()
    yield user_id
    async with async_session() as db:
        await db.execute(
            delete(LearnedSkill).where(LearnedSkill.user_id == user_id)
        )
        await db.commit()


def _build_skill(user_id: str, **overrides) -> LearnedSkill:
    """Helper — minimal LearnedSkill that satisfies all NOT NULLs."""
    defaults = dict(
        user_id=user_id,
        name=f"trivial_{uuid.uuid4().hex[:8]}",
        description="x",
        content="def f(): return 1",
        content_format=SkillContentFormat.PYTHON_TOOL,
        status=SkillStatus.CANDIDATE,
        source=SkillSource.AUTO_GENERATED,
    )
    defaults.update(overrides)
    return LearnedSkill(**defaults)


@pytest.mark.asyncio
async def test_tool_profile_defaults_to_pure_for_new_rows(
    _seeded_user_for_tool_profile,
):
    """Every existing call-site instantiates LearnedSkill without
    tool_profile — they must keep getting "pure", or every pre-V3 row
    suddenly runs through the V3 sandbox path. Hard-pin this default."""
    user_id = _seeded_user_for_tool_profile
    async with async_session() as db:
        skill = _build_skill(user_id)
        db.add(skill)
        await db.commit()
        skill_id = skill.id

    async with async_session() as db:
        read_back = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert read_back.tool_profile == SkillToolProfile.PURE


@pytest.mark.asyncio
async def test_tool_profile_io_persists_roundtrip(
    _seeded_user_for_tool_profile,
):
    """When the caller explicitly sets tool_profile="io" (J6.b/J7 will do
    this for V3-generated tools), the value round-trips through the DB
    unchanged. Sanity check that the ALTER-TABLE DDL didn't silently
    truncate or normalize."""
    user_id = _seeded_user_for_tool_profile
    async with async_session() as db:
        skill = _build_skill(user_id, tool_profile=SkillToolProfile.IO)
        db.add(skill)
        await db.commit()
        skill_id = skill.id

    async with async_session() as db:
        read_back = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert read_back.tool_profile == SkillToolProfile.IO
