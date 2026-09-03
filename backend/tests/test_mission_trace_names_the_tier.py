# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_trace_names_the_tier.py
# @brief      La colonne `model_used` de la trace nomme le tier réellement
#             appelé, elle ne dit plus « medium » quoi qu'il arrive.
# @license    MIT
# =============================================================================
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionPlan, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service

    await init_db()
    uid = f"test_tier_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(user_id=uid, title="Tier", goal="g")
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep, MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


_PLAN = {"steps": [{"id": "s1", "description": "Cherche des catalogues."}]}


@pytest.mark.asyncio
async def test_la_ligne_act_nomme_le_tier(mission) -> None:
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    uid, mid = mission

    class _Acteur:
        def __init__(self):
            self.n = 0

        async def ainvoke(self, messages, **_kw):
            self.n += 1
            if self.n == 1:
                return types.SimpleNamespace(content="", tool_calls=[
                    {"name": "web_search", "args": {"query": "x"}, "id": "c1"},
                ])
            return types.SimpleNamespace(content="fait", tool_calls=[])

    async def _llms(**_kw):
        return _Acteur(), [], []

    async def _d(*_a, **_kw):
        return "8 résultats", True

    originaux = (mn._get_actor_llms, mn.dispatch_tool)
    mn._get_actor_llms, mn.dispatch_tool = _llms, _d
    try:
        await mn.act_node({"mission_id": mid, "user_id": uid, "goal": "g",
                           "plan_json": _PLAN, "plan_text": "# Plan"})
    finally:
        mn._get_actor_llms, mn.dispatch_tool = originaux

    lignes = [s for s in await mission_service.list_steps(mid) if s.phase == "act"]
    assert lignes and lignes[-1].model_used.startswith("complex-tier")


@pytest.mark.asyncio
async def test_la_ligne_eval_nomme_le_tier(mission) -> None:
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    uid, mid = mission

    class _Juge:
        async def ainvoke(self, messages, **_kw):
            return types.SimpleNamespace(content=json.dumps(
                {"success": True, "reason": "fait", "all_done": False},
            ))

    original = mn._get_evaluator_llm
    mn._get_evaluator_llm = lambda **_kw: _Juge()
    try:
        await mn.eval_node({
            "mission_id": mid, "user_id": uid, "goal": "g",
            "plan_json": _PLAN, "current_step_id": "s1",
            "last_tool_name": "web_search", "last_tool_input": {"query": "x"},
            "last_tool_output": "8 résultats",
        })
    finally:
        mn._get_evaluator_llm = original

    lignes = [s for s in await mission_service.list_steps(mid) if s.phase == "eval"]
    assert lignes and lignes[-1].model_used == "complex-tier"
