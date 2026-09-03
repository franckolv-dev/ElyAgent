# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_tokens_and_tier.py
# @brief      C1a (audit 16/07, §6.4/§6.6) — exactitude missions : le budget
#             de tokens compte la consommation RÉELLE, et le tier LLM du
#             mandat (D3) est appliqué par les nœuds plan/act/eval.
# @license    MIT
# =============================================================================
"""Exactitude des contrats missions.

Avant C1a :
  - ``Mission.tokens_used`` restait à 0 (7 missions, 50 itérations max
    observées, zéro token compté) → ``check_budget`` donnait une fausse
    assurance (§6.4) ;
  - ``mandate.llm_tier`` était validé et stocké mais JAMAIS lu — les nœuds
    utilisaient ``MEDIUM`` en dur, contredisant la décision D3 (§6.6).

Run with:  cd backend && python -m pytest tests/test_mission_tokens_and_tier.py -v
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.database import async_session, init_db

EMAIL_SPEC_BASE = "version: 2\nmandate:\n  tools_allow: [email]\n"
STEPS = "steps:\n  - id: s1\n    do: x"


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


@pytest_asyncio.fixture
async def _uid():
    from app.models.user import User
    uid = "c1a_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _mission(uid: str, *, spec: str | None = None,
                   budget_tokens: int = 50_000) -> str:
    from app.services import mission_service
    m = await mission_service.create_mission(
        user_id=uid, title="M", goal="g", spec_yaml=spec,
        budget_tokens=budget_tokens,
    )
    return m.id


# ── 1. Budget de tokens réel (§6.4) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_tokens_used_accumulates(_uid):
    from app.services import mission_service
    mid = await _mission(_uid)
    await mission_service.add_tokens_used(mid, 150)
    await mission_service.add_tokens_used(mid, 50)
    m = await mission_service.get_mission(mid)
    assert m.tokens_used == 200


@pytest.mark.asyncio
async def test_log_mission_llm_usage_feeds_budget(_uid):
    """Chaque invocation LLM du graphe mission doit alimenter le compteur."""
    from app.agent.missions import nodes as mnodes
    from app.services import mission_service

    mid = await _mission(_uid)
    resp = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 50},
        content="ok",
    )
    await mnodes._log_mission_llm_usage(resp, _uid, mid, "plan", llm=None)
    m = await mission_service.get_mission(mid)
    assert m.tokens_used == 150


@pytest.mark.asyncio
async def test_log_mission_llm_usage_heuristic_fallback(_uid):
    """Sans usage_metadata (certains modèles locaux) : heuristique 4 c/token."""
    from app.agent.missions import nodes as mnodes
    from app.services import mission_service

    mid = await _mission(_uid)
    resp = SimpleNamespace(usage_metadata=None, content="x" * 400)
    await mnodes._log_mission_llm_usage(resp, _uid, mid, "act", llm=None)
    m = await mission_service.get_mission(mid)
    assert m.tokens_used >= 200  # 2 × (400 // 4)


@pytest.mark.asyncio
async def test_token_budget_becomes_enforceable(_uid):
    """Avec des tokens réels, check_budget (heartbeat + /tick) mord enfin."""
    from app.agent.missions import nodes as mnodes
    from app.services import mission_service

    mid = await _mission(_uid, budget_tokens=100)
    resp = SimpleNamespace(
        usage_metadata={"input_tokens": 90, "output_tokens": 20},
        content="ok",
    )
    await mnodes._log_mission_llm_usage(resp, _uid, mid, "plan", llm=None)
    reason = await mission_service.check_budget(mid)
    assert reason is not None and "token" in reason


# ── 2. Tier LLM du mandat (D3, §6.6) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_mission_llm_tier_without_mandate_is_complex(_uid):
    """Une mission est un travail agentique multi-étapes : le tier COMPLEX.

    Le 31/08/2026, la mission « Prospection LKDN » a tourné entièrement sur
    la tête du tier MEDIUM — Gemma 4 26B en local — : 10 à 22 s par appel,
    et un acteur qui rouvre le même onglet quatre fois. Le chat, lui, envoie
    toute demande utilisateur au tier COMPLEX depuis la #287.
    """
    from app.agent.missions.nodes import _mission_llm_tier
    from app.services.llm_provider import ComplexityTier
    mid = await _mission(_uid)
    assert await _mission_llm_tier(mid) == ComplexityTier.COMPLEX


@pytest.mark.asyncio
async def test_mission_llm_tier_mandate_defaults_to_complex(_uid, monkeypatch):
    """D3 : sous mandat actif sans llm_tier explicite → COMPLEX forcé."""
    from app.agent.missions.nodes import _mission_llm_tier
    from app.config import get_settings
    from app.services import mission_service
    from app.services.llm_provider import ComplexityTier

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    mid = await _mission(_uid, spec=EMAIL_SPEC_BASE + STEPS)
    await mission_service.set_autonomy_state(mid, "active")
    assert await _mission_llm_tier(mid) == ComplexityTier.COMPLEX


@pytest.mark.asyncio
async def test_mission_llm_tier_mandate_override(_uid, monkeypatch):
    from app.agent.missions.nodes import _mission_llm_tier
    from app.config import get_settings
    from app.services import mission_service
    from app.services.llm_provider import ComplexityTier

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    spec = EMAIL_SPEC_BASE + "  llm_tier: medium\n" + STEPS
    mid = await _mission(_uid, spec=spec)
    await mission_service.set_autonomy_state(mid, "active")
    assert await _mission_llm_tier(mid) == ComplexityTier.MEDIUM


@pytest.mark.asyncio
async def test_mission_llm_tier_flag_off_falls_back_to_complex(_uid, monkeypatch):
    """Mission mandatée créée flag ON, puis flag ÉTEINT ⇒ load_active_mandate
    renvoie None ⇒ repli sur le tier des missions sans mandat : COMPLEX."""
    from app.agent.missions.nodes import _mission_llm_tier
    from app.config import get_settings
    from app.services import mission_service
    from app.services.llm_provider import ComplexityTier

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    mid = await _mission(_uid, spec=EMAIL_SPEC_BASE + STEPS)
    await mission_service.set_autonomy_state(mid, "active")
    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", False)
    assert await _mission_llm_tier(mid) == ComplexityTier.COMPLEX


# ── 3. Les getters LLM propagent le tier ────────────────────────────────────


def test_planner_and_evaluator_getters_pass_tier(monkeypatch):
    import app.services.llm_provider as lp
    from app.agent.missions import nodes as mnodes
    from app.services.llm_provider import ComplexityTier

    seen: list = []
    monkeypatch.setattr(lp, "get_llm_for_tier",
                        lambda tier, **_kw: seen.append(tier) or "LLM")

    assert mnodes._get_planner_llm(tier=ComplexityTier.COMPLEX) == "LLM"
    assert mnodes._get_evaluator_llm(tier=ComplexityTier.COMPLEX) == "LLM"
    assert seen == [ComplexityTier.COMPLEX, ComplexityTier.COMPLEX]


@pytest.mark.asyncio
async def test_actor_getter_passes_tier(monkeypatch):
    import app.services.llm_provider as lp
    import app.skills as skills_mod
    from app.agent.missions import nodes as mnodes
    from app.services.llm_provider import ComplexityTier

    seen: list = []

    class _Llm:
        def bind_tools(self, _tools):
            return "BOUND"

    async def _no_filter(_tools, _hint, _goal, _desc, mission_id="", step_tools=()):
        return []

    async def _no_learned(tools, _uid):
        return tools

    monkeypatch.setattr(lp, "get_llm_for_tier",
                        lambda tier, **_kw: seen.append(tier) or _Llm())
    monkeypatch.setattr(lp, "get_fallback_llms", lambda: [])
    monkeypatch.setattr(skills_mod, "get_skill_registry",
                        lambda: SimpleNamespace(all_tools=[]))
    monkeypatch.setattr(mnodes, "_filter_tools_for_step", _no_filter)
    import app.services.learning.learned_tools_runtime as ltr
    monkeypatch.setattr(ltr, "append_learned_tools", _no_learned)

    primary, fallbacks, _tools = await mnodes._get_actor_llms(
        user_id="u", tier=ComplexityTier.COMPLEX,
    )
    assert primary == "BOUND"
    assert seen == [ComplexityTier.COMPLEX]
