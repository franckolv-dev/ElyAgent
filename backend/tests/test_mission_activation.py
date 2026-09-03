# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_activation.py
# @brief      Missions autonomes J6 (C2) — activation HUMAINE du mandat
#             (pending_validation → active) + API workspace (carnet, journal,
#             compteurs journaliers) pour le viewer.
# @license    MIT
# =============================================================================
"""J6 — le moteur d'autonomie s'allume ICI, et seulement ici.

D6 : un mandat est validé UNE fois, explicitement, par l'humain. Rien
d'autre ne fait passer ``pending_validation → active`` (la reprise J3 ne
concerne que ``paused_* → active``, mandat déjà validé).

Run with:  cd backend && python -m pytest tests/test_mission_activation.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.database import async_session, init_db

MANDATE_SPEC = (
    "version: 2\n"
    "mandate:\n"
    "  tools_allow: [email]\n"
    "steps:\n"
    "  - id: s1\n"
    "    do: x"
)


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


@pytest.fixture(autouse=True)
def _ws_dir(tmp_path, monkeypatch):
    """Workspace des missions dans un tmp — le défaut /app/data/missions est
    un chemin conteneur (même montage que test_mission_workspace.py)."""
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))


class _U:
    def __init__(self, uid: str):
        self.id = uid


@pytest_asyncio.fixture
async def _uid():
    from app.models.user import User
    uid = "j6_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _pending_mission(uid: str, monkeypatch) -> str:
    """Mission mandatée fraîche : autonomy_state='pending_validation'."""
    from app.config import get_settings
    from app.services import mission_service
    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    m = await mission_service.create_mission(
        user_id=uid, title="M", goal="g", spec_yaml=MANDATE_SPEC,
    )
    assert m.autonomy_state == "pending_validation"
    return m.id


# ── 0. C6 — l'arrêt d'urgence révoque le mandat ─────────────────────────────


@pytest.mark.asyncio
async def test_abort_revokes_autonomy_state(_uid, monkeypatch):
    """Micro-backlog C6 (vu au test réel du 19/07) : après un arrêt
    d'urgence, autonomy_state restait 'active' — badge « Autonomie
    active » sur une mission avortée. L'abort doit révoquer le mandat."""
    from app.routers.missions import activate_mission_mandate
    from app.services import mission_service

    mid = await _pending_mission(_uid, monkeypatch)
    await activate_mission_mandate(mid, current_user=_U(_uid))
    m = await mission_service.get_mission(mid)
    assert m.autonomy_state == "active"

    out = await mission_service.abort_mission(mid, reason="test kill switch")
    assert out.status == "aborted"
    assert out.autonomy_state == "revoked"
    # Persisté, pas seulement sur l'objet retourné
    m2 = await mission_service.get_mission(mid)
    assert m2.autonomy_state == "revoked"
    # Et le gate d'enforcement ne voit plus de mandat actif
    assert await mission_service.load_active_mandate(mid) is None


@pytest.mark.asyncio
async def test_abort_without_mandate_leaves_autonomy_none(_uid, monkeypatch):
    from app.config import get_settings
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    m = await mission_service.create_mission(user_id=_uid, title="M", goal="goal")
    assert m.autonomy_state is None
    out = await mission_service.abort_mission(m.id, reason="test")
    assert out.status == "aborted"
    assert out.autonomy_state is None


# ── 1. POST /missions/{id}/activate ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_happy_path_pending_to_active(_uid, monkeypatch):
    from app.routers.missions import activate_mission_mandate
    from app.services import mission_workspace as ws

    mid = await _pending_mission(_uid, monkeypatch)
    out = await activate_mission_mandate(mid, current_user=_U(_uid))
    assert out.autonomy_state == "active"
    assert out.mandate_json  # le résumé du mandat est exposé au frontend
    # L'activation initialise le carnet (branchement J4 de set_autonomy_state).
    assert ws.read_carnet(mid)


@pytest.mark.asyncio
async def test_activate_refused_when_flag_off(_uid, monkeypatch):
    from app.config import get_settings
    from app.routers.missions import activate_mission_mandate

    mid = await _pending_mission(_uid, monkeypatch)
    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", False)
    with pytest.raises(HTTPException) as ei:
        await activate_mission_mandate(mid, current_user=_U(_uid))
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_activate_requires_mandate(_uid, monkeypatch):
    from app.config import get_settings
    from app.routers.missions import activate_mission_mandate
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    m = await mission_service.create_mission(user_id=_uid, title="M", goal="g")
    with pytest.raises(HTTPException) as ei:
        await activate_mission_mandate(m.id, current_user=_U(_uid))
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_activate_conflict_when_already_active(_uid, monkeypatch):
    from app.routers.missions import activate_mission_mandate

    mid = await _pending_mission(_uid, monkeypatch)
    await activate_mission_mandate(mid, current_user=_U(_uid))
    with pytest.raises(HTTPException) as ei:
        await activate_mission_mandate(mid, current_user=_U(_uid))
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_activate_acl_other_user_404(_uid, monkeypatch):
    from app.routers.missions import activate_mission_mandate

    mid = await _pending_mission(_uid, monkeypatch)
    with pytest.raises(HTTPException) as ei:
        await activate_mission_mandate(mid, current_user=_U("intrus"))
    assert ei.value.status_code == 404


# ── 2. GET /missions/{id}/workspace ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_returns_carnet_journal_and_counters(_uid, monkeypatch):
    from app.routers.missions import activate_mission_mandate, get_mission_workspace
    from app.services import mission_workspace as ws
    from app.services.mission_budget import incr_tool_action

    mid = await _pending_mission(_uid, monkeypatch)
    await activate_mission_mandate(mid, current_user=_U(_uid))
    ws.journal_append(mid, {"tool": "email_send", "outcome": "success"})
    await incr_tool_action(mid)

    out = await get_mission_workspace(mid, current_user=_U(_uid))
    assert out.carnet and "Objectif" in out.carnet
    assert out.journal and out.journal[-1]["tool"] == "email_send"
    assert out.counters and out.counters["tool_actions"] == 1


@pytest.mark.asyncio
async def test_workspace_empty_mission_is_clean(_uid, monkeypatch):
    """Mission sans workspace (jamais activée) : réponse vide propre."""
    from app.config import get_settings
    from app.routers.missions import get_mission_workspace
    from app.services import mission_service

    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    m = await mission_service.create_mission(user_id=_uid, title="M", goal="g")
    out = await get_mission_workspace(m.id, current_user=_U(_uid))
    assert out.carnet is None
    assert out.journal == []
    assert out.counters is None


@pytest.mark.asyncio
async def test_workspace_acl_other_user_404(_uid, monkeypatch):
    from app.routers.missions import get_mission_workspace

    mid = await _pending_mission(_uid, monkeypatch)
    with pytest.raises(HTTPException) as ei:
        await get_mission_workspace(mid, current_user=_U("intrus"))
    assert ei.value.status_code == 404


# ── 3. MissionOut expose l'état d'autonomie ─────────────────────────────────


@pytest.mark.asyncio
async def test_mission_out_exposes_autonomy_fields(_uid, monkeypatch):
    from app.routers.missions import MissionOut
    from app.services import mission_service

    mid = await _pending_mission(_uid, monkeypatch)
    m = await mission_service.get_mission(mid)
    out = MissionOut.model_validate(m)
    assert out.autonomy_state == "pending_validation"
    assert out.mandate_json and "email" in out.mandate_json
