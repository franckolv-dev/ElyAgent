# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learned_tool_usage_bump.py
# @brief      Sprint 4d (gap J1) — chaque invocation d'un python_tool pur
#             bumpe use_count/last_used_at (gate « invocations »).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pin du bump d'usage à l'invocation.

Découvert en réel le 11 juin : 11 appels fibonacci → use_count=0. Le bump
n'existait que pour les playbooks (skill_view) ; les python_tools purs
n'étaient comptés nulle part — la gate invocations de la graduation ne
pouvait jamais passer.

Run with:  cd backend && python -m pytest tests/test_learned_tool_usage_bump.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning.learned_tools_runtime import _wrap_with_usage_bump
from app.services.learning.tool_loader import compile_tool_source

_SOURCE = '''
from __future__ import annotations

from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="bump_echo",
    skill_display_name="Echo",
    skill_description="Echo input.",
    skill_icon="📣",
    enabled_by_default=False,
)
@tool
def bump_echo(text: str) -> str:
    """Echo the input text back."""
    return f"echo: {text}"
'''


@pytest_asyncio.fixture
async def seeded_skill():
    await init_db()
    from app.models.user import User
    uid = "u_bump"
    async with async_session() as db:
        if (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none() is None:
            db.add(User(id=uid, username="bump_test_user",
                        email="u_bump@test.local", hashed_password="x"))
            await db.commit()
    skill = LearnedSkill(
        id=str(uuid.uuid4()), user_id=uid, name="bump_echo",
        description="t", content=_SOURCE,
        content_format=SkillContentFormat.PYTHON_TOOL,
        frontmatter_json="{}", tool_profile="pure", status=SkillStatus.ACTIVE,
        source=SkillSource.AUTO_GENERATED, iteration_count=1,
        from_failure_case_ids="[]", use_count=0,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    async with async_session() as db:
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
    yield skill
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.commit()


async def _use_count(skill_id: str) -> tuple[int, object]:
    async with async_session() as db:
        row = await db.get(LearnedSkill, skill_id)
        return int(row.use_count or 0), row.last_used_at


@pytest.mark.asyncio
async def test_each_invocation_bumps_use_count(seeded_skill):
    res = compile_tool_source(_SOURCE)
    assert res.ok
    tool = _wrap_with_usage_bump(res.tool, seeded_skill.id)

    # Le bump est attendu/bloqué jusqu'au commit AVANT le retour de l'outil :
    # chaque invocation est comptée de façon déterministe, sans empiler des
    # écritures concurrentes non attendues (ancienne flakiness CI : 1 au lieu
    # de 2 — task fire-and-forget collectée avant commit / race read-write).
    out = await tool.ainvoke({"text": "salut"})
    assert out == "echo: salut"          # le wrap ne change pas le résultat
    count, last_used = await _use_count(seeded_skill.id)
    assert count == 1                    # committé dès le retour, pas « plus tard »
    assert last_used is not None

    out2 = await tool.ainvoke({"text": "re"})
    assert out2 == "echo: re"
    count, last_used = await _use_count(seeded_skill.id)
    assert count == 2
    assert last_used is not None


@pytest.mark.asyncio
async def test_bump_failure_never_breaks_the_call(seeded_skill, monkeypatch):
    """Le compteur est du confort ; l'appel de l'outil est sacré."""
    import app.services.learning.active_skills as active_skills

    async def _boom(_skill_id: str) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(active_skills, "bump_skill_usage", _boom)
    res = compile_tool_source(_SOURCE)
    tool = _wrap_with_usage_bump(res.tool, seeded_skill.id)
    assert await tool.ainvoke({"text": "ok"}) == "echo: ok"
