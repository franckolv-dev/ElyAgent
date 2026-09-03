# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reversible_surfaces.py
# @brief      Substrat / J2 — surfaces d'annulation (outils + API /me).
# @license    MIT
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

import app.services.compensation_registry as creg
from app.services import journal_service as js
from app.agent.tools.reversible_tool import (
    list_revertible_actions,
    revert_action,
    undo_last_action,
)


@pytest_asyncio.fixture
async def db_ready():
    from app.database import init_db
    await init_db()


@pytest.fixture
def journal_on(monkeypatch):
    monkeypatch.setattr(js, "_enabled", lambda: True)


@pytest.fixture
def stub_drive(monkeypatch):
    calls: list[tuple[dict, str]] = []

    async def fake_revert(comp_args, user_id):
        calls.append((dict(comp_args), user_id))

    monkeypatch.setitem(
        creg._REGISTRY,
        "restore_from_trash",
        creg.Compensation(
            name="restore_from_trash",
            capture=lambda args, result: {"file_id": (args or {}).get("file_id")},
            revert=fake_revert,
        ),
    )
    return calls


async def _cleanup(uid: str):
    from sqlalchemy import delete
    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    async with async_session() as db:
        await db.execute(
            delete(ReversibleActionRecord).where(ReversibleActionRecord.user_id == uid)
        )
        await db.commit()


async def _get(rid: str):
    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    async with async_session() as db:
        return await db.get(ReversibleActionRecord, rid)


def _fake_user(uid: str):
    class _U:
        id = uid
    return _U()


# ── Outils model-facing ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tool_empty(db_ready, journal_on):
    out = await list_revertible_actions.coroutine(user_id=f"u_{uuid.uuid4().hex}")
    assert "Aucune action annulable" in out


@pytest.mark.asyncio
async def test_revert_tool_partial_id(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        listed = await list_revertible_actions.coroutine(user_id=uid)
        assert rid[:8] in listed
        out = await revert_action.coroutine(record_id=rid[:8], user_id=uid)   # id PARTIEL
        assert "annulée" in out.lower()
        assert stub_drive == [({"file_id": "F1"}, uid)]
        assert (await _get(rid)).status == "reverted"
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_last_tool_takes_most_recent(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        await js.record_reversible("drive_delete_file", {"file_id": "A"}, "ok", uid, "fpA")
        await js.record_reversible("drive_delete_file", {"file_id": "B"}, "ok", uid, "fpB")
        out = await undo_last_action.coroutine(user_id=uid)
        assert "annulée" in out.lower()
        assert stub_drive == [({"file_id": "B"}, uid)]      # la plus récente
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_revert_tool_unknown_id(db_ready, journal_on, stub_drive):
    out = await revert_action.coroutine(record_id="deadbeef", user_id=f"u_{uuid.uuid4().hex}")
    assert "introuvable" in out.lower()
    assert stub_drive == []


@pytest.mark.asyncio
async def test_revert_tool_cross_user_isolated(db_ready, journal_on, stub_drive):
    a, b = f"u_{uuid.uuid4().hex}", f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", a, "fp")
        out = await revert_action.coroutine(record_id=rid, user_id=b)   # autre user
        assert "introuvable" in out.lower()
        assert stub_drive == []
        assert (await _get(rid)).status == "recorded"      # action de A intacte
    finally:
        await _cleanup(a)
        await _cleanup(b)


# ── API /api/me/reversible-actions ───────────────────────────────────────


@pytest.mark.asyncio
async def test_api_list_and_undo(db_ready, journal_on, stub_drive):
    from app.routers.reversible_actions import list_my_reversible_actions, undo_my_action
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        listed = await list_my_reversible_actions(user=_fake_user(uid))
        assert [x.id for x in listed] == [rid]
        assert listed[0].capability_id == "drive_delete_file"
        res = await undo_my_action(record_id=rid, user=_fake_user(uid))
        assert res.ok is True
        assert stub_drive == [({"file_id": "F1"}, uid)]
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_api_undo_unknown_404(db_ready, journal_on):
    from fastapi import HTTPException
    from app.routers.reversible_actions import undo_my_action
    with pytest.raises(HTTPException) as ei:
        await undo_my_action(record_id="nope", user=_fake_user("u1"))
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_api_undo_cross_user_404(db_ready, journal_on, stub_drive):
    from fastapi import HTTPException
    from app.routers.reversible_actions import undo_my_action
    a, b = f"u_{uuid.uuid4().hex}", f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", a, "fp")
        with pytest.raises(HTTPException) as ei:
            await undo_my_action(record_id=rid, user=_fake_user(b))
        assert ei.value.status_code == 404           # forbidden → 404 (pas de fuite)
        assert stub_drive == []
    finally:
        await _cleanup(a)
        await _cleanup(b)


@pytest.mark.asyncio
async def test_api_undo_expired_409(db_ready, journal_on, stub_drive, monkeypatch):
    from fastapi import HTTPException
    from app.routers.reversible_actions import undo_my_action
    monkeypatch.setattr(js, "_ttl_seconds", lambda: -5)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        with pytest.raises(HTTPException) as ei:
            await undo_my_action(record_id=rid, user=_fake_user(uid))
        assert ei.value.status_code == 409
    finally:
        await _cleanup(uid)


# ── Câblage ──────────────────────────────────────────────────────────────


def test_router_registered_in_main_app():
    import app.main as main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert any(p.startswith("/api/me/reversible-actions") for p in paths)


def test_tools_in_user_id_tools_for_injection():
    # Les 3 outils prennent user_id (InjectedToolArg) → ils DOIVENT être dans
    # USER_ID_TOOLS pour que tool_node injecte l'identité.
    from app.agent.tool_sets import USER_ID_TOOLS
    assert {"list_revertible_actions", "revert_action", "undo_last_action"} <= USER_ID_TOOLS


def test_skill_registered():
    import app.skills.builtin.reversible_skill  # noqa: F401 — register() au niveau module
    from app.skills.registry import get_skill_registry
    assert "reversible_actions" in get_skill_registry()._skills


def test_reversible_tool_names_empty_when_flag_off(monkeypatch):
    # Flag OFF (il est ON par défaut depuis le 03/09/2026) → aucun outil
    # d'annulation lié (zéro coût de prompt).
    from app.config import get_settings
    from app.agent.toolset_profiles import _reversible_tool_names
    monkeypatch.setattr(get_settings(), "reversible_journal_enabled", False)
    assert _reversible_tool_names() == set()


def test_reversible_tool_names_present_when_flag_on(monkeypatch):
    from app.config import get_settings
    from app.agent.toolset_profiles import _reversible_tool_names, _REVERSIBLE_TOOL_NAMES
    monkeypatch.setattr(get_settings(), "reversible_journal_enabled", True)
    assert _reversible_tool_names() == set(_REVERSIBLE_TOOL_NAMES)


def test_resolve_profile_unions_reversible_dynamically(monkeypatch):
    from app.agent import toolset_profiles as tp

    class _T:
        def __init__(self, n):
            self.name = n

    all_tools = [_T(n) for n in ("notes_list", *tp._REVERSIBLE_TOOL_NAMES)]
    # Flag ON simulé → les 3 outils sont liés.
    monkeypatch.setattr(tp, "_reversible_tool_names", lambda: set(tp._REVERSIBLE_TOOL_NAMES))
    bound_on = {t.name for t in tp.resolve_profile_tools("default", all_tools)}
    assert set(tp._REVERSIBLE_TOOL_NAMES) <= bound_on
    # Flag OFF simulé → aucun.
    monkeypatch.setattr(tp, "_reversible_tool_names", lambda: set())
    bound_off = {t.name for t in tp.resolve_profile_tools("default", all_tools)}
    assert not (set(tp._REVERSIBLE_TOOL_NAMES) & bound_off)
