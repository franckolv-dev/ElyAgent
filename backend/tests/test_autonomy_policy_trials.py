import json
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from sqlalchemy import select
from tests.test_patch_service import _db, _seed_user, _fake_admin
from app.database import async_session
from app.models.learned_skill import LearnedSkill
from app.models.autonomy import ProcedureTrial
from app.services.procedure_trials import record_trial
from app.services.autonomy_policy import permission_for, should_notify
from app.routers.autonomy import save_preferences, PreferencesInput, toggle_procedure, Enable


@pytest.mark.asyncio
async def test_strongest_user_restriction_wins_and_is_scoped():
    uid = await _seed_user()
    other = await _seed_user()
    await save_preferences(PreferencesInput(read="confirm", system="deny", notifications="none"), _fake_admin(uid))
    assert await permission_for(uid, "web_search") == "confirm"
    assert await permission_for(uid, "desktop_read_file") == "deny"
    assert await permission_for(other, "web_search") == "inherit"
    assert not await should_notify(uid, "failed")


async def skill(uid, pinned=False):
    async with async_session() as db:
        s = LearnedSkill(
            user_id=uid,
            name="research",
            description="Recherche",
            content="Appeler web_search",
            status="active",
            pinned=pinned,
        )
        db.add(s)
        await db.commit()
        return s


@pytest.mark.asyncio
async def test_three_distinct_failures_suspend_and_reactivation():
    uid = await _seed_user()
    s = await skill(uid)
    await record_trial(uid, s.id, "one", "failed")
    await record_trial(uid, s.id, "one", "failed")
    await record_trial(uid, s.id, "two", "failed")
    async with async_session() as db:
        assert (await db.get(LearnedSkill, s.id)).status == "active"
    await record_trial(uid, s.id, "three", "failed")
    async with async_session() as db:
        assert (await db.get(LearnedSkill, s.id)).status == "stale"
        assert (
            len((await db.execute(select(ProcedureTrial).where(ProcedureTrial.skill_id == s.id))).scalars().all()) == 3
        )
    await toggle_procedure(s.id, Enable(enabled=True), _fake_admin(uid))
    async with async_session() as db:
        assert (await db.get(LearnedSkill, s.id)).status == "active"


@pytest.mark.asyncio
async def test_pinned_procedure_reports_failures_without_auto_suspend():
    uid = await _seed_user()
    s = await skill(uid, True)
    for i in range(3):
        await record_trial(uid, s.id, str(i), "failed")
    async with async_session() as db:
        assert (await db.get(LearnedSkill, s.id)).status == "active"
