# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_strict_autonomy.py
# @brief      Missions autonomes J5 — mode decide (D2), consignes de mandat,
#             anti-boucle (D4). Flag OFF ou pas de mandat ⇒ comportement inchangé.
# @license    MIT
# =============================================================================
"""Missions autonomes J5 — autonomie stricte (cadrage D2 + D4).

`on_unforeseen: decide` : Ely refuse un outil hors mandat et choisit une
alternative DANS l'allowlist (pas de HITL) ; les 2 consignes D2 sont gravées
au prompt d'action ; l'anti-boucle refuse un 4e appel identique en échec et
force un changement de stratégie (jamais un arrêt).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def _user_j5():
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.conversation import Conversation, Message
    from app.models.mission import Mission, MissionDailyCounter, MissionStep
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j5u_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        mids = [r[0] for r in (await db.execute(
            select(Mission.id).where(Mission.user_id == uid))).all()]
        if mids:
            await db.execute(delete(MissionDailyCounter).where(
                MissionDailyCounter.mission_id.in_(mids)))
            await db.execute(delete(MissionStep).where(
                MissionStep.mission_id.in_(mids)))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        cids = [r[0] for r in (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid))).all()]
        if cids:
            await db.execute(delete(Message).where(Message.conversation_id.in_(cids)))
            await db.execute(delete(Conversation).where(Conversation.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest_asyncio.fixture
async def _mission_with_steps(_user_j5):
    """Une mission réelle du user J5 + un helper pour ajouter des steps act."""
    from app.services import mission_service

    m = await mission_service.create_mission(user_id=_user_j5, title="t", goal="g")

    async def _add(tool_name, tool_input, success):
        await mission_service.add_step(
            m.id, phase="act", thought="x", tool_name=tool_name,
            tool_input=tool_input, tool_output="o", success=success,
        )

    return m.id, _user_j5, _add


@pytest.fixture
def _ws_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    return tmp_path / "missions"


@pytest.fixture
def _stub_tool(monkeypatch):
    """Installe un outil stub dans le SkillRegistry (le registry est vide en
    test — discovery non lancée). Renvoie un dict qui compte les invocations."""
    ran = {"count": 0}

    class _Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, args):
            ran["count"] += 1
            return "résultat ok"

    class _FakeRegistry:
        def __init__(self, tools):
            self._tools = tools

        @property
        def all_tools(self):
            return self._tools

    def _install(name):
        reg = _FakeRegistry([_Tool(name)])
        monkeypatch.setattr("app.skills.get_skill_registry", lambda: reg)
        return ran

    return _install


async def _mandated_mission(uid, monkeypatch, mode: str, allow="email"):
    from app.config import get_settings
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    spec = (
        "version: 2\n"
        "mandate:\n"
        f"  tools_allow: [{allow}]\n"
        f"  on_unforeseen: {mode}\n"
        "steps:\n  - id: s1\n    do: x"
    )
    m = await mission_service.create_mission(
        user_id=uid, title="Chaîne", goal="gérer", spec_yaml=spec,
    )
    await mission_service.set_autonomy_state(m.id, "active")
    return m.id


# ─────────────────────────────────────────────────────────────────────────
# Task 1 — module pur mission_antiloop
# ─────────────────────────────────────────────────────────────────────────


def test_call_signature_is_order_insensitive():
    from app.services.mission_antiloop import call_signature

    assert call_signature("t", {"a": 1, "b": 2}) == call_signature("t", {"b": 2, "a": 1})
    assert call_signature("t", {"a": 1}) != call_signature("t", {"a": 2})
    assert call_signature("t1", {}) != call_signature("t2", {})
    assert call_signature("t", None) == call_signature("t", {})


@pytest.mark.asyncio
async def test_consecutive_identical_failures_counts_run(_mission_with_steps):
    from app.services.mission_antiloop import consecutive_identical_failures

    mid, _uid, add = _mission_with_steps
    await add("gmail_send_email", {"to": "x@y.z"}, False)
    await add("gmail_send_email", {"to": "x@y.z"}, False)
    await add("gmail_send_email", {"to": "x@y.z"}, False)
    n = await consecutive_identical_failures(mid, "gmail_send_email", {"to": "x@y.z"})
    assert n == 3


@pytest.mark.asyncio
async def test_a_success_or_different_call_resets_the_run(_mission_with_steps):
    from app.services.mission_antiloop import consecutive_identical_failures

    mid, _uid, add = _mission_with_steps
    await add("gmail_send_email", {"to": "x@y.z"}, False)
    await add("gmail_send_email", {"to": "x@y.z"}, True)     # succès → coupe
    await add("gmail_send_email", {"to": "x@y.z"}, False)
    n = await consecutive_identical_failures(mid, "gmail_send_email", {"to": "x@y.z"})
    assert n == 1

    await add("web_search", {"q": "autre"}, False)           # appel différent en tête
    n2 = await consecutive_identical_failures(mid, "gmail_send_email", {"to": "x@y.z"})
    assert n2 == 0


# ─────────────────────────────────────────────────────────────────────────
# Task 2 — gate decide + consignes D2
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_refuses_out_of_mandate_without_hitl(_ws_env, _user_j5, _stub_tool, monkeypatch):
    """Hors mandat en mode decide : refus sec de CET outil, PAS de HITL,
    message qui pousse à choisir une alternative dans l'allowlist."""
    from app.agent.missions import nodes

    called = {"hitl": False}

    class _Spy:
        async def request_validation(self, description, user_id, channel="web"):
            called["hitl"] = True
            return "allow", None
    monkeypatch.setattr("app.services.hitl_manager.get_hitl_manager", lambda: _Spy())

    # github_* est hors de l'allowlist [email] ; on l'enregistre pour passer
    # le garde « outil inconnu » et atteindre le gate du mandat.
    ran = _stub_tool("github_create_issue")
    mid = await _mandated_mission(_user_j5, monkeypatch, "decide", allow="email")
    out, ok = await nodes.dispatch_tool("github_create_issue", {"t": "x"}, "c1",
                                        user_id=_user_j5, mission_id=mid)
    assert ok is False
    assert called["hitl"] is False               # AUCUN HITL en mode decide
    assert ran["count"] == 0                      # l'outil hors mandat n'a PAS tourné
    assert "alternative" in out.lower() or "mandat" in out.lower()


@pytest.mark.asyncio
async def test_escalate_still_uses_hitl_out_of_mandate(_ws_env, _user_j5, _stub_tool, monkeypatch):
    """Mode escalate (défaut) : hors mandat → HITL forcé (inchangé J2)."""
    from app.agent.missions import nodes

    called = {"hitl": False}

    class _Spy:
        async def request_validation(self, description, user_id, channel="web"):
            called["hitl"] = True
            return "deny", "timeout"
    monkeypatch.setattr("app.services.hitl_manager.get_hitl_manager", lambda: _Spy())

    _stub_tool("github_create_issue")
    mid = await _mandated_mission(_user_j5, monkeypatch, "escalate", allow="email")
    await nodes.dispatch_tool("github_create_issue", {"t": "x"}, "c1",
                              user_id=_user_j5, mission_id=mid)
    assert called["hitl"] is True                # escalade préservée


def test_strict_directives_only_in_decide_mode():
    from app.agent.missions.nodes import _strict_autonomy_directives
    from app.services.mission_spec import MissionMandate

    d_escalate = _strict_autonomy_directives(
        MissionMandate(tools_allow=("email",), on_unforeseen="escalate"))
    d_decide = _strict_autonomy_directives(
        MissionMandate(tools_allow=("email",), on_unforeseen="decide"))
    # rappel sécurité présent dans les deux (contenu externe = données)
    assert "données" in d_escalate and "données" in d_decide
    # les 2 consignes D2 seulement en decide
    assert "loi française" in d_decide and "loi française" not in d_escalate
    assert "carnet" in d_decide.lower()


# ─────────────────────────────────────────────────────────────────────────
# Task 3 — anti-boucle branchée dans act_node
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_antiloop_blocks_fourth_identical_call(_ws_env, _user_j5, monkeypatch):
    """3 échecs identiques déjà en base + un 4e appel identique proposé par
    le LLM ⇒ act_node NE dispatche PAS, renvoie un échec instructif et
    incrémente consecutive_failures (→ replan)."""
    from app.agent.missions import nodes
    from app.services import mission_service

    mid = await _mandated_mission(_user_j5, monkeypatch, "decide", allow="web")
    # 3 échecs identiques déjà consignés
    for _ in range(3):
        await mission_service.add_step(
            mid, phase="act", thought="x", tool_name="web_search",
            tool_input={"q": "boucle"}, tool_output="err", success=False,
        )

    # Le LLM (stubé) ré-émet EXACTEMENT le même appel
    dispatched = {"n": 0}

    async def _never(*a, **k):
        dispatched["n"] += 1
        return "ne devrait pas être appelé", True
    monkeypatch.setattr(nodes, "dispatch_tool", _never)

    class _Resp:
        content = ""
        tool_calls = [{"name": "web_search", "args": {"q": "boucle"},
                       "id": "call-1"}]

    async def _fake_actor_llms(**kwargs):
        class _LLM:
            async def ainvoke(self, msgs):
                return _Resp()
        return _LLM(), [], []
    monkeypatch.setattr(nodes, "_get_actor_llms", _fake_actor_llms)

    state = {
        "mission_id": mid, "user_id": _user_j5, "goal": "g",
        "plan_json": {"steps": [{"id": "1", "description": "cherche",
                                 "status": "pending"}]},
        "plan_text": "1. cherche", "consecutive_failures": 0,
    }
    out = await nodes.act_node(state)
    assert dispatched["n"] == 0                       # AUCUN dispatch
    assert out["last_eval_success"] is False
    assert out["consecutive_failures"] == 1          # nudge vers replan
    assert "stratégie" in (out["last_eval_reason"] or "").lower()


@pytest.mark.asyncio
async def test_antiloop_inactive_without_mandate(_ws_env, _user_j5, monkeypatch):
    """Sans mandat actif : l'anti-boucle est un no-op — le dispatch a lieu
    même après 3 échecs identiques (filet supervisé = replan seul)."""
    from app.agent.missions import nodes
    from app.services import mission_service

    m = await mission_service.create_mission(user_id=_user_j5, title="t", goal="g")
    for _ in range(3):
        await mission_service.add_step(
            m.id, phase="act", thought="x", tool_name="web_search",
            tool_input={"q": "boucle"}, tool_output="err", success=False,
        )

    dispatched = {"n": 0}

    async def _yes(*a, **k):
        dispatched["n"] += 1
        return "ok", True
    monkeypatch.setattr(nodes, "dispatch_tool", _yes)

    class _Resp:
        content = ""
        tool_calls = [{"name": "web_search", "args": {"q": "boucle"}, "id": "c"}]

    async def _fake_actor_llms(**kwargs):
        class _LLM:
            async def ainvoke(self, msgs):
                return _Resp()
        return _LLM(), [], []
    monkeypatch.setattr(nodes, "_get_actor_llms", _fake_actor_llms)

    state = {
        "mission_id": m.id, "user_id": _user_j5, "goal": "g",
        "plan_json": {"steps": [{"id": "1", "description": "c", "status": "pending"}]},
        "plan_text": "1. c", "consecutive_failures": 0,
    }
    await nodes.act_node(state)
    assert dispatched["n"] == 1                       # dispatch bien effectué
