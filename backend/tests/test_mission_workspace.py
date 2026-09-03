# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_workspace.py
# @brief      Missions autonomes J4 — workspace de mission : journal JSONL avec
#             rotation, CARNET.md atomique, injection contexte, branchements.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Missions autonomes J4 — pins du workspace (cadrage D5).

`data/missions/<id>/` = la mémoire de travail longue durée d'une mission
autonome : `artefacts/` (fichiers produits), `journal.jsonl` (append-only,
rotation), `CARNET.md` (relu à chaque planification, section Pause écrite
par le disjoncteur J3, leçons promues en mémoire durable à la complétion).
Flag OFF ou mission sans mandat actif ⇒ AUCUN fichier créé.
"""
from __future__ import annotations

import json as _json
import uuid

import pytest
import pytest_asyncio


@pytest.fixture
def _ws(tmp_path, monkeypatch):
    """Base workspace isolée + rotation basse pour les tests."""
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    monkeypatch.setenv("MISSIONS_JOURNAL_MAX_BYTES", "500")
    return tmp_path / "missions"


# ─────────────────────────────────────────────────────────────────────────
# Module pur — validation, journal, carnet
# ─────────────────────────────────────────────────────────────────────────


def test_workspace_dir_rejects_traversal(_ws):
    from app.services.mission_workspace import workspace_dir

    for bad in ("../x", "a/b", "", "a" * 80, "id with spaces", ".hidden"):
        with pytest.raises(ValueError):
            workspace_dir(bad)
    # un uuid4 passe
    assert workspace_dir(str(uuid.uuid4())).name


def test_ensure_workspace_creates_artefacts(_ws):
    from app.services.mission_workspace import ensure_workspace

    mid = str(uuid.uuid4())
    ws = ensure_workspace(mid)
    assert ws.is_dir() and (ws / "artefacts").is_dir()
    assert ws.parent == _ws


def test_journal_append_tail_and_rotation(_ws):
    from app.services.mission_workspace import (
        journal_append,
        read_journal_tail,
        workspace_dir,
    )

    mid = str(uuid.uuid4())
    journal_append(mid, {"tool": "t1", "ok": True})
    journal_append(mid, {"tool": "t2", "ok": False})
    tail = read_journal_tail(mid, n=10)
    assert [e["tool"] for e in tail] == ["t1", "t2"]
    assert all("ts" in e for e in tail)          # horodatage ajouté

    # Rotation : MAX=500 octets → quelques grosses lignes suffisent
    for i in range(20):
        journal_append(mid, {"tool": f"big{i}", "pad": "x" * 100})
    ws = workspace_dir(mid)
    assert (ws / "journal.1.jsonl").exists()      # archive créée
    assert (ws / "journal.jsonl").stat().st_size < 500 + 200
    # le tail lit le fichier courant sans casser
    assert read_journal_tail(mid, n=3)


def test_carnet_write_read_roundtrip_and_cap(_ws):
    from app.services.mission_workspace import read_carnet, write_carnet

    mid = str(uuid.uuid4())
    assert read_carnet(mid) is None
    write_carnet(mid, "# Carnet\n\ncontenu")
    assert read_carnet(mid).startswith("# Carnet")

    # Cap 64 Ko : la FIN est préservée (le récent prime)
    big = ("ancien\n" * 8000) + "FIN_RECENTE"
    write_carnet(mid, big)
    stored = read_carnet(mid)
    assert len(stored.encode()) <= 64 * 1024 + 100
    assert stored.endswith("FIN_RECENTE")


def test_carnet_append_section(_ws):
    from app.services.mission_workspace import (
        carnet_append_section,
        read_carnet,
        write_carnet,
    )

    mid = str(uuid.uuid4())
    write_carnet(mid, "# Carnet de bord\n\n## Leçons\n")
    carnet_append_section(mid, "Leçons", "- toujours vérifier le quota")
    carnet_append_section(mid, "Pause", "- pausée à 12h (seuil)")   # section absente → créée
    c = read_carnet(mid)
    assert "- toujours vérifier le quota" in c
    assert "## Pause" in c and "- pausée à 12h (seuil)" in c
    # la leçon est bien SOUS ## Leçons (avant ## Pause)
    assert c.index("vérifier le quota") < c.index("## Pause")


def test_init_carnet_idempotent(_ws):
    from app.services.mission_spec import parse_mission_spec
    from app.services.mission_workspace import init_carnet, read_carnet

    mid = str(uuid.uuid4())
    spec = parse_mission_spec(
        "version: 2\nmandate:\n  tools_allow: [youtube]\nsteps:\n  - id: s\n    do: x"
    )
    init_carnet(mid, "Chaîne YT", "gérer la chaîne", spec.mandate)
    c = read_carnet(mid)
    assert "# Carnet de bord" in c and "## Objectif" in c
    assert "## Mandat" in c and "youtube" in c
    assert "## Leçons" in c
    # idempotent : un carnet existant n'est PAS écrasé
    from app.services.mission_workspace import carnet_append_section
    carnet_append_section(mid, "Leçons", "- précieuse leçon")
    init_carnet(mid, "Chaîne YT", "gérer la chaîne", spec.mandate)
    assert "- précieuse leçon" in read_carnet(mid)


def test_carnet_context_block(_ws):
    from app.services.mission_workspace import carnet_context_block, write_carnet

    mid = str(uuid.uuid4())
    assert carnet_context_block(mid) is None      # pas de carnet → None
    write_carnet(mid, "# Carnet\n" + ("ligne ancienne\n" * 500) + "ETAT_RECENT")
    blk = carnet_context_block(mid, max_chars=1000)
    assert "CARNET DE BORD" in blk
    assert len(blk) <= 1000 + 100
    assert "ETAT_RECENT" in blk                   # la fin survit à la troncature


# ─────────────────────────────────────────────────────────────────────────
# Branchements — journal outil, pause→carnet, activation, injection, leçons
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def _user_j4():
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.conversation import Conversation, Message
    from app.models.mission import Mission, MissionDailyCounter
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j4_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from app.models.execution_outcome import ExecutionOutcome
        from app.models.mission import MissionStepRun

        mids = [r[0] for r in (await db.execute(
            select(Mission.id).where(Mission.user_id == uid))).all()]
        if mids:
            await db.execute(delete(MissionDailyCounter).where(
                MissionDailyCounter.mission_id.in_(mids)))
            await db.execute(delete(MissionStepRun).where(
                MissionStepRun.mission_id.in_(mids)))
        # complete_mission spawn record_mission_outcome → ligne FK sur users
        await db.execute(delete(ExecutionOutcome).where(
            ExecutionOutcome.user_id == uid))
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


async def _mandated_mission(uid, monkeypatch, budgets_yaml: str = ""):
    from app.config import get_settings
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    spec = "version: 2\nmandate:\n  tools_allow: [email, youtube]\n"
    if budgets_yaml:
        spec += f"  budgets:\n{budgets_yaml}\n"
    spec += "steps:\n  - id: s1\n    do: x"
    m = await mission_service.create_mission(
        user_id=uid, title="Chaîne YT", goal="gérer la chaîne", spec_yaml=spec,
    )
    await mission_service.set_autonomy_state(m.id, "active")
    return m.id


@pytest.fixture
def _stub_tool(monkeypatch):
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


@pytest.mark.asyncio
async def test_dispatch_journals_under_mandate(_ws, _user_j4, _stub_tool, monkeypatch):
    from app.agent.missions import nodes
    from app.services.mission_workspace import read_journal_tail

    _stub_tool("gmail_list_emails")
    mid = await _mandated_mission(_user_j4, monkeypatch)
    await nodes.dispatch_tool("gmail_list_emails", {}, "c1",
                              user_id=_user_j4, mission_id=mid)
    tail = read_journal_tail(mid)
    assert tail and tail[-1]["tool"] == "gmail_list_emails"
    assert tail[-1]["ok"] is True and "duration_s" in tail[-1]


@pytest.mark.asyncio
async def test_no_mandate_no_files(_ws, _user_j4, _stub_tool, monkeypatch):
    from app.agent.missions import nodes
    from app.services import mission_service

    _stub_tool("notes_list")
    m = await mission_service.create_mission(user_id=_user_j4, title="s", goal="g")
    await nodes.dispatch_tool("notes_list", {}, "c1",
                              user_id=_user_j4, mission_id=m.id)
    assert not (_ws / m.id).exists()      # aucun workspace créé


@pytest.mark.asyncio
async def test_activation_initializes_carnet(_ws, _user_j4, monkeypatch):
    from app.services.mission_workspace import read_carnet

    mid = await _mandated_mission(_user_j4, monkeypatch)
    c = read_carnet(mid)
    assert c is not None and "## Objectif" in c and "gérer la chaîne" in c
    assert "youtube" in c                  # le mandat est lisible


@pytest.mark.asyncio
async def test_pause_writes_carnet_section(_ws, _user_j4, _stub_tool, monkeypatch):
    from app.agent.missions import nodes
    from app.services import mission_service
    from app.services.mission_workspace import read_carnet

    class _DenyHitl:
        async def request_validation(self, description, user_id):
            return "deny", "timeout"
    monkeypatch.setattr("app.services.hitl_manager.get_hitl_manager", lambda: _DenyHitl())

    _stub_tool("gmail_list_emails")
    mid = await _mandated_mission(_user_j4, monkeypatch,
                                  budgets_yaml="    daily_tool_actions_notify: 1")
    await mission_service.start_mission(mid)
    await nodes.dispatch_tool("gmail_list_emails", {}, "c1",
                              user_id=_user_j4, mission_id=mid)
    c = read_carnet(mid)
    assert "## Pause" in c and "seuil" in c.lower()


@pytest.mark.asyncio
async def test_mandate_carnet_block_helper(_ws, _user_j4, monkeypatch):
    from app.agent.missions.nodes import _mandate_carnet_block
    from app.services import mission_service

    mid = await _mandated_mission(_user_j4, monkeypatch)
    blk = await _mandate_carnet_block(mid)
    assert "CARNET DE BORD" in blk         # mandat actif + carnet initialisé

    # mission sans mandat → bloc vide
    m = await mission_service.create_mission(user_id=_user_j4, title="s", goal="g")
    assert await _mandate_carnet_block(m.id) == ""


@pytest.mark.asyncio
async def test_complete_promotes_lessons(_ws, _user_j4, monkeypatch):
    from app.services import mission_service
    from app.services.mission_workspace import carnet_append_section

    stored = {}

    class _FakeMM:
        async def store_memory(self, content, user_id, conversation_id="", extra_payload=None):
            stored["content"] = content
            stored["extra"] = extra_payload

    monkeypatch.setattr("app.services.memory_manager.get_memory_manager", lambda: _FakeMM())

    mid = await _mandated_mission(_user_j4, monkeypatch)
    carnet_append_section(mid, "Leçons", "- publier le mardi marche mieux")
    await mission_service.start_mission(mid)
    await mission_service.complete_mission(mid, "terminée")
    # la promotion est spawnée — laisser la boucle la traiter
    import asyncio
    await asyncio.sleep(0.05)
    assert "publier le mardi" in stored.get("content", "")
    assert stored["extra"]["source"] == "mission_carnet"
