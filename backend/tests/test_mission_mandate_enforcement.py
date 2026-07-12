# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate_enforcement.py
# @brief      Missions autonomes J2 — enforcement du mandat : mapping
#             outil→famille, chargement du mandat actif, gate dans dispatch_tool.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J2 — pins de l'enforcement.

Cadrage : docs_internes/cadrage_missions_autonomes.md (§3.2, D1/D2).
Le mandat DÉPLACE le HITL de l'action vers le grant : sous mandat actif,
famille autorisée ⇒ pas de HITL ; noyau interdit ⇒ refus sec ; hors
mandat ⇒ escalade au HITL humain. J2 = escalate ; decide = J5.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def _user_j2():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j2g_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from sqlalchemy import select

        from app.models.mission import MissionDailyCounter

        # J3 : sous mandat actif, dispatch_tool incrémente un compteur du jour
        # (FK missions) → le purger avant les missions.
        mids = [r[0] for r in (await db.execute(
            select(Mission.id).where(Mission.user_id == uid))).all()]
        if mids:
            await db.execute(delete(MissionDailyCounter).where(
                MissionDailyCounter.mission_id.in_(mids)))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Mapping outil → famille
# ─────────────────────────────────────────────────────────────────────────


def test_tool_family_known_prefixes() -> None:
    from app.services.mission_tool_families import tool_family

    assert tool_family("gmail_send_email") == "email"
    assert tool_family("gmail_list_emails") == "email"
    assert tool_family("drive_create_file") == "drive"
    assert tool_family("calendar_create_event") == "calendar"
    assert tool_family("browser_navigate") == "web"
    assert tool_family("web_search") == "web"
    assert tool_family("desktop_read_file") == "files"
    assert tool_family("scheduler_create_task") == "scheduler"
    assert tool_family("tasks_create") == "tasks"
    assert tool_family("contacts_search") == "contacts"
    assert tool_family("github_repo_stats") == "github"
    assert tool_family("notes_create") == "notes"
    assert tool_family("vision_analyze_image") == "vision"


def test_tool_family_forbidden_prefixes() -> None:
    from app.services.mission_spec import MANDATE_FORBIDDEN_FAMILIES
    from app.services.mission_tool_families import tool_family

    assert tool_family("ssh_execute") == "ssh"
    assert tool_family("vault_unlock") == "vault"
    assert tool_family("mcp_call_tool") == "mcp"
    assert tool_family("os_click") == "system"
    # tous bien dans le noyau interdit du contrat J1
    for t in ("ssh_execute", "vault_unlock", "mcp_call_tool", "os_click"):
        assert tool_family(t) in MANDATE_FORBIDDEN_FAMILIES


def test_tool_family_unknown_is_none() -> None:
    from app.services.mission_tool_families import tool_family

    # Un outil non mappé ⇒ None ⇒ le gate escalade (fail-closed).
    assert tool_family("some_brand_new_tool") is None
    assert tool_family("orchestrate") is None   # méta/univ — non rattaché à une famille


def test_escalate_always_set_covers_escape_hatches() -> None:
    from app.services.mission_tool_families import MANDATE_ESCALATE_ALWAYS

    # Sans annulation possible : toujours escalader, même famille autorisée.
    assert "gmail_empty_trash" in MANDATE_ESCALATE_ALWAYS
    assert "gmail_raw_api_call" in MANDATE_ESCALATE_ALWAYS
    assert "drive_raw_api_call" in MANDATE_ESCALATE_ALWAYS


# ─────────────────────────────────────────────────────────────────────────
# Reconstruction du mandat + chargement de l'actif
# ─────────────────────────────────────────────────────────────────────────


def test_mandate_json_roundtrip() -> None:
    from app.services.mission_spec import (
        mandate_from_json,
        mandate_to_json,
        parse_mission_spec,
    )

    spec = parse_mission_spec(
        "version: 2\nmandate:\n  tools_allow: [youtube, drive]\n"
        "  on_unforeseen: decide\n  llm_tier: medium\n"
        "steps:\n  - id: s1\n    do: x"
    )
    restored = mandate_from_json(mandate_to_json(spec.mandate))
    assert restored == spec.mandate  # frozen dataclass ⇒ égalité structurelle


@pytest.mark.asyncio
async def test_load_active_mandate_gated_by_flag_and_state(monkeypatch) -> None:
    from sqlalchemy import delete

    from app.config import get_settings
    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j2_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    try:
        m = await mission_service.create_mission(
            user_id=uid, title="YT", goal="gérer",
            spec_yaml="version: 2\nmandate:\n  tools_allow: [youtube]\n"
                      "steps:\n  - id: s1\n    do: x",
        )
        # pending_validation (défaut J1) ⇒ pas encore actif
        assert await mission_service.load_active_mandate(m.id) is None

        # activé ⇒ le mandat est chargé
        await mission_service.set_autonomy_state(m.id, "active")
        mandate = await mission_service.load_active_mandate(m.id)
        assert mandate is not None and mandate.tools_allow == ("youtube",)

        # flag OFF ⇒ inerte même si actif (fail-closed)
        monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", False)
        assert await mission_service.load_active_mandate(m.id) is None
    finally:
        async with async_session() as db:
            await db.execute(delete(Mission).where(Mission.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Le gate — matrice mandat × outils
# ─────────────────────────────────────────────────────────────────────────


async def _mission_with_mandate(uid, tools_allow, monkeypatch, on_unforeseen="escalate"):
    """Crée une mission au mandat ACTIF et renvoie son id."""
    from app.config import get_settings
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    allow = ", ".join(tools_allow)
    m = await mission_service.create_mission(
        user_id=uid, title="M", goal="g",
        spec_yaml=f"version: 2\nmandate:\n  tools_allow: [{allow}]\n"
                  f"  on_unforeseen: {on_unforeseen}\n"
                  f"steps:\n  - id: s1\n    do: x",
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
    """Un outil bidon dispatchable dont le nom est paramétrable par test.

    `SkillRegistry.all_tools` est une property en lecture seule → on remplace
    `get_skill_registry` par un faux registre (résolu à l'appel dans
    dispatch_tool via `from app.skills import get_skill_registry`)."""
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
async def test_gate_allowed_family_bypasses_hitl(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Famille autorisée + outil critique ⇒ PAS de HITL, exécution directe."""
    from app.agent.missions import nodes

    _stub_tool("gmail_send_email")  # critique (ALWAYS_CRITICAL/NEVER_AUTONOMOUS)
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    out, ok = await nodes.dispatch_tool(
        "gmail_send_email", {"to": "x@y.z"}, "call1",
        user_id=_user_j2, mission_id=mid,
    )
    assert ok is True
    assert _capture_hitl["asked"] == 0   # le mandat a couvert l'action


@pytest.mark.asyncio
async def test_gate_forbidden_family_hard_refused(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Noyau interdit ⇒ refus sec, jamais exécuté, jamais escaladé."""
    from app.agent.missions import nodes

    ran = _stub_tool("ssh_execute")
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    out, ok = await nodes.dispatch_tool(
        "ssh_execute", {"cmd": "ls"}, "call1",
        user_id=_user_j2, mission_id=mid,
    )
    assert ok is False
    assert "interdit" in out.lower()
    assert ran["count"] == 0
    assert _capture_hitl["asked"] == 0


@pytest.mark.asyncio
async def test_gate_out_of_mandate_escalates(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Famille hors allowlist ⇒ escalade au HITL humain (mode escalate)."""
    from app.agent.missions import nodes

    _stub_tool("drive_delete_file")   # famille 'drive', pas dans l'allowlist [email]
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    out, ok = await nodes.dispatch_tool(
        "drive_delete_file", {"file_id": "abc"}, "call1",
        user_id=_user_j2, mission_id=mid,
    )
    assert _capture_hitl["asked"] == 1   # l'humain a été sollicité
    assert ok is True                    # _capture_hitl répond 'allow'


@pytest.mark.asyncio
async def test_gate_escape_hatch_always_escalates(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Escape-hatch (empty_trash) ⇒ escalade même si 'email' est autorisé."""
    from app.agent.missions import nodes

    _stub_tool("gmail_empty_trash")
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    await nodes.dispatch_tool(
        "gmail_empty_trash", {}, "call1", user_id=_user_j2, mission_id=mid,
    )
    assert _capture_hitl["asked"] == 1


@pytest.mark.asyncio
async def test_gate_universal_tool_never_escalates(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Substrat (find_tool) ⇒ toujours autorisé sous mandat, jamais de HITL."""
    from app.agent.missions import nodes

    _stub_tool("find_tool")
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    out, ok = await nodes.dispatch_tool(
        "find_tool", {"query": "youtube"}, "call1",
        user_id=_user_j2, mission_id=mid,
    )
    assert ok is True
    assert _capture_hitl["asked"] == 0


@pytest.mark.asyncio
async def test_gate_benign_out_of_mandate_still_escalates(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Containment : un outil bénin (web_search) HORS mandat escalade quand
    même — le mandat borne le rayon d'action, pas seulement les actions risquées."""
    from app.agent.missions import nodes

    _stub_tool("web_search")   # non critique, mais famille 'web' ∉ [email]
    mid = await _mission_with_mandate(_user_j2, ["email"], monkeypatch)

    await nodes.dispatch_tool(
        "web_search", {"query": "x"}, "call1", user_id=_user_j2, mission_id=mid,
    )
    assert _capture_hitl["asked"] == 1


@pytest.mark.asyncio
async def test_no_mandate_mission_unchanged(_user_j2, _capture_hitl, _stub_tool, monkeypatch):
    """Mission SANS mandat ⇒ chemin actuel : outil critique ⇒ HITL sollicité."""
    from app.agent.missions import nodes
    from app.services import mission_service

    _stub_tool("gmail_send_email")
    m = await mission_service.create_mission(
        user_id=_user_j2, title="legacy", goal="g",
    )  # pas de spec, pas de mandat
    await nodes.dispatch_tool(
        "gmail_send_email", {"to": "stranger@x.z"}, "call1",
        user_id=_user_j2, mission_id=m.id,
    )
    assert _capture_hitl["asked"] == 1   # comportement supervisé inchangé
