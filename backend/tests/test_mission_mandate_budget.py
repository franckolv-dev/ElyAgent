# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate_budget.py
# @brief      Missions autonomes J3 — disjoncteurs D4 : compteurs journaliers,
#             seuils de notification, pause propre + snapshot, reprise.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Missions autonomes J3 — pins des disjoncteurs.

Cadrage D4 (arbitrage Franck 11/07) : pas de plafond bloquant — des seuils
de NOTIFICATION (500 actions / 100 appels LLM par jour, surchargeables par
mandat). Franchissement (≥) ⇒ HITL « continuer ? » ; allow ⇒ acquitté pour
la journée ; deny/timeout (30 min) ⇒ pause propre + snapshot + reprise
possible là où la mission s'est arrêtée. Compteurs PERSISTÉS (un restart ne
remet pas le jour à zéro).
"""
from __future__ import annotations

import json as _json
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def _user_j3():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionDailyCounter
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j3_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from sqlalchemy import select

        from app.models.conversation import Conversation, Message

        mids = [r[0] for r in (await db.execute(
            select(Mission.id).where(Mission.user_id == uid))).all()]
        if mids:
            await db.execute(delete(MissionDailyCounter).where(
                MissionDailyCounter.mission_id.in_(mids)))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        # Les notifications de pause (_notify_terminal) créent une conversation
        # « [Missions] » + des messages FK à l'utilisateur → purger avant le User.
        cids = [r[0] for r in (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid))).all()]
        if cids:
            await db.execute(delete(Message).where(Message.conversation_id.in_(cids)))
            await db.execute(delete(Conversation).where(Conversation.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Compteurs journaliers
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_counters_increment_and_persist(_user_j3):
    from app.services import mission_budget, mission_service

    m = await mission_service.create_mission(user_id=_user_j3, title="c", goal="g")
    c1 = await mission_budget.incr_tool_action(m.id)
    assert (c1.tool_actions, c1.llm_calls) == (1, 0)
    await mission_budget.incr_llm_call(m.id)
    c2 = await mission_budget.incr_tool_action(m.id)
    assert (c2.tool_actions, c2.llm_calls) == (2, 1)
    # lecture indépendante (persisté, pas en mémoire)
    c3 = await mission_budget.get_today(m.id)
    assert (c3.tool_actions, c3.llm_calls) == (2, 1)
    assert c3.day == mission_budget.today_key()
    assert c3.tool_ack is False and c3.llm_ack is False


@pytest.mark.asyncio
async def test_ack_threshold(_user_j3):
    from app.services import mission_budget, mission_service

    m = await mission_service.create_mission(user_id=_user_j3, title="a", goal="g")
    await mission_budget.incr_tool_action(m.id)
    await mission_budget.ack_threshold(m.id, "tool")
    c = await mission_budget.get_today(m.id)
    assert c.tool_ack is True and c.llm_ack is False


# ─────────────────────────────────────────────────────────────────────────
# Disjoncteur — franchissement, acquittement, pause, reprise
# ─────────────────────────────────────────────────────────────────────────


async def _mission_with_mandate(uid, tools_allow, monkeypatch, budgets_yaml: str = ""):
    """Mission au mandat ACTIF (budgets optionnels), renvoie son id."""
    from app.config import get_settings
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    allow = ", ".join(tools_allow)
    spec = f"version: 2\nmandate:\n  tools_allow: [{allow}]\n"
    if budgets_yaml:
        spec += f"  budgets:\n{budgets_yaml}\n"
    spec += "steps:\n  - id: s1\n    do: x"
    m = await mission_service.create_mission(
        user_id=uid, title="M", goal="g", spec_yaml=spec,
    )
    await mission_service.set_autonomy_state(m.id, "active")
    return m.id


@pytest.fixture
def _capture_hitl(monkeypatch):
    """Capture si le HITL a été SOLLICITÉ et force une décision 'allow'."""
    calls = {"asked": 0}

    class _FakeHitl:
        async def request_validation(self, description, user_id):
            calls["asked"] += 1
            return "allow", ""

    monkeypatch.setattr(
        "app.services.hitl_manager.get_hitl_manager", lambda: _FakeHitl()
    )
    return calls


@pytest.fixture
def _stub_tool(monkeypatch):
    """Un outil bidon dispatchable (registry remplacé, cf. J2)."""
    ran = {"count": 0}

    class _Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, args):
            ran["count"] += 1
            return "ok"

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


@pytest.mark.asyncio
async def test_breach_allow_acks_and_continues(_user_j3, _capture_hitl, _stub_tool, monkeypatch):
    """Seuil atteint + réponse 'allow' ⇒ acquitté, l'outil s'exécute, plus de
    re-prompt le même jour."""
    from app.agent.missions import nodes
    from app.services import mission_budget

    ran = _stub_tool("gmail_list_emails")   # famille email, non critique
    mid = await _mission_with_mandate(
        _user_j3, ["email"], monkeypatch,
        budgets_yaml="    daily_tool_actions_notify: 1",
    )
    out, ok = await nodes.dispatch_tool("gmail_list_emails", {}, "c1",
                                        user_id=_user_j3, mission_id=mid)
    assert ok is True and ran["count"] == 1
    assert _capture_hitl["asked"] == 1          # 1er franchissement → prompt
    c = await mission_budget.get_today(mid)
    assert c.tool_ack is True
    out, ok = await nodes.dispatch_tool("gmail_list_emails", {}, "c2",
                                        user_id=_user_j3, mission_id=mid)
    assert ok is True and _capture_hitl["asked"] == 1   # acquitté : pas de re-prompt


@pytest.mark.asyncio
async def test_breach_deny_pauses_with_snapshot(_user_j3, _stub_tool, monkeypatch):
    """Refus (ou timeout ⇒ deny) ⇒ pause propre : outil NON exécuté, statut
    paused, autonomy_state=paused_budget, snapshot JSON complet."""
    from app.agent.missions import nodes
    from app.services import mission_service

    class _DenyHitl:
        async def request_validation(self, description, user_id):
            return "deny", "timeout"
    monkeypatch.setattr("app.services.hitl_manager.get_hitl_manager", lambda: _DenyHitl())

    ran = _stub_tool("gmail_list_emails")
    mid = await _mission_with_mandate(
        _user_j3, ["email"], monkeypatch,
        budgets_yaml="    daily_tool_actions_notify: 1",
    )
    await mission_service.start_mission(mid)    # draft → planning (pausable)
    out, ok = await nodes.dispatch_tool("gmail_list_emails", {}, "c1",
                                        user_id=_user_j3, mission_id=mid)
    assert ok is False and ran["count"] == 0
    m = await mission_service.get_mission(mid)
    assert m.status == "paused"
    assert m.autonomy_state == "paused_budget"
    snap = _json.loads(m.autonomy_pause_json)
    assert snap["reason"].startswith("budget_tool_actions")
    assert snap["counters"]["tool_actions"] >= 1


@pytest.mark.asyncio
async def test_resume_restores_active_and_keeps_counters(_user_j3, _stub_tool, monkeypatch):
    """start_mission sur une mission paused_budget ⇒ active, compteurs intacts."""
    from app.agent.missions import nodes
    from app.services import mission_budget, mission_service

    class _DenyHitl:
        async def request_validation(self, description, user_id):
            return "deny", "timeout"
    monkeypatch.setattr("app.services.hitl_manager.get_hitl_manager", lambda: _DenyHitl())

    _stub_tool("gmail_list_emails")
    mid = await _mission_with_mandate(
        _user_j3, ["email"], monkeypatch,
        budgets_yaml="    daily_tool_actions_notify: 1",
    )
    await mission_service.start_mission(mid)
    await nodes.dispatch_tool("gmail_list_emails", {}, "c1",
                              user_id=_user_j3, mission_id=mid)   # → pause

    await mission_service.start_mission(mid)    # reprise (paused → planning)
    m = await mission_service.get_mission(mid)
    assert m.status == "planning" and m.autonomy_state == "active"
    c = await mission_budget.get_today(mid)
    assert c.tool_actions >= 1                  # pas de reset


@pytest.mark.asyncio
async def test_no_mandate_no_counting(_user_j3, _capture_hitl, _stub_tool, monkeypatch):
    """Mission sans mandat ⇒ aucun compteur écrit, aucun check."""
    from app.agent.missions import nodes
    from app.services import mission_budget, mission_service

    _stub_tool("notes_list")   # bénin, pas de HITL
    m = await mission_service.create_mission(user_id=_user_j3, title="s", goal="g")
    await nodes.dispatch_tool("notes_list", {}, "c1",
                              user_id=_user_j3, mission_id=m.id)
    assert await mission_budget.get_today(m.id) is None
    assert _capture_hitl["asked"] == 0


@pytest.mark.asyncio
async def test_llm_usage_increments_counter(_user_j3, monkeypatch):
    """_log_mission_llm_usage incrémente llm_calls (flag ON)."""
    from app.agent.missions.nodes import _log_mission_llm_usage
    from app.config import get_settings
    from app.services import mission_budget, mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    m = await mission_service.create_mission(user_id=_user_j3, title="l", goal="g")

    class _Resp:
        usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        content = "x"

    class _Llm:
        model = "test-model"

    await _log_mission_llm_usage(_Resp(), _user_j3, m.id, "plan", _Llm())
    c = await mission_budget.get_today(m.id)
    assert c is not None and c.llm_calls == 1


@pytest.mark.asyncio
async def test_migration_0019_adds_table_and_column_to_legacy_db(tmp_path, monkeypatch) -> None:
    """Piège d'adoption (pattern 0002/0018) : base existante jamais vue par
    Alembic ⇒ stamp baseline + upgrade doit créer la table compteurs ET la
    colonne snapshot."""
    import sqlite3
    import types

    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, goal TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )

    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    cols = {r[1] for r in check.execute("PRAGMA table_info(missions)")}
    tables = {r[0] for r in check.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check.close()
    assert "autonomy_pause_json" in cols
    assert "mission_daily_counters" in tables
