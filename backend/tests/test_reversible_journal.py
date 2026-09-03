# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reversible_journal.py
# @brief      Substrat / J1 — Reversible Action Journal (record / undo).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

import app.services.compensation_registry as creg
from app.services import journal_service as js


@pytest_asyncio.fixture
async def db_ready():
    from app.database import init_db
    await init_db()


@pytest.fixture
def journal_on(monkeypatch):
    """Active le journal au niveau du service (indépendant de pydantic)."""
    monkeypatch.setattr(js, "_enabled", lambda: True)


@pytest.fixture
def stub_drive(monkeypatch):
    """Remplace la compensation Drive réelle par un stub qui enregistre l'appel
    (garde une `capture` réaliste = file_id only)."""
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


# ── Flag OFF = no-op strict (défaut réel) ────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_is_noop(db_ready, monkeypatch):
    # ON par défaut depuis le 03/09/2026 : on teste le no-op en l'ÉTEIGNANT.
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "reversible_journal_enabled", False)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible(
            "drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp1"
        )
        assert rid is None                       # flag OFF → rien
        assert await js.list_reversible(uid) == []
    finally:
        await _cleanup(uid)


# ── Record → undo (cas nominal) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_then_undo_restores(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible(
            "drive_delete_file", {"file_id": "F1"}, "trashed", uid, "fp1"
        )
        assert rid is not None
        rec = await _get(rid)
        assert rec.status == "recorded" and rec.capability_id == "drive_delete_file"

        res = await js.undo(rid, uid)
        assert res["ok"] is True
        assert stub_drive == [({"file_id": "F1"}, uid)]   # compensation appelée
        assert (await _get(rid)).status == "reverted"
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_capture_keeps_only_file_id(db_ready, journal_on, stub_drive):
    """Minimisation : seul file_id est stocké (pas de secret/PII)."""
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible(
            "drive_delete_file",
            {"file_id": "F9", "user_token": "SECRET", "name": "budget.xlsx"},
            "trashed", uid, "fp2",
        )
        stored = json.loads((await _get(rid)).compensation_args)
        assert stored == {"file_id": "F9"}
    finally:
        await _cleanup(uid)


# ── Fail-closed ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_wrong_owner_forbidden(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, "someone_else")
        assert res == {"ok": False, "reason": "forbidden"}
        assert stub_drive == []                          # compensation JAMAIS appelée
        assert (await _get(rid)).status == "recorded"    # entrée intacte
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_unknown_record(db_ready, journal_on):
    res = await js.undo("does_not_exist", "u1")
    assert res == {"ok": False, "reason": "not_found"}


@pytest.mark.asyncio
async def test_undo_expired_refused(db_ready, journal_on, stub_drive, monkeypatch):
    uid = f"u_{uuid.uuid4().hex}"
    monkeypatch.setattr(js, "_ttl_seconds", lambda: -5)   # entrée déjà expirée
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, uid)
        assert res == {"ok": False, "reason": "expired"}
        assert stub_drive == []
        assert (await _get(rid)).status == "expired"
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_double_undo_is_noop(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        first = await js.undo(rid, uid)
        second = await js.undo(rid, uid)
        assert first["ok"] is True
        assert second == {"ok": False, "reason": "not_revertible:reverted"}
        assert len(stub_drive) == 1                       # compensation une SEULE fois
    finally:
        await _cleanup(uid)


# ── No-op : pas de compensation / handle inconnu ─────────────────────────


@pytest.mark.asyncio
async def test_tool_without_compensation_is_noop(db_ready, journal_on):
    # web_search : manifeste sans compensation → rien à journaliser.
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("web_search", {"query": "x"}, "ok", uid, "fp")
        assert rid is None
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_declared_but_unregistered_compensation_is_noop(db_ready, journal_on, monkeypatch):
    # Le manifeste de drive_delete_file déclare restore_from_trash, mais si le
    # handle n'est pas (ou plus) enregistré → no-op (pas d'entrée orpheline).
    monkeypatch.delitem(creg._REGISTRY, "restore_from_trash", raising=False)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        assert rid is None
    finally:
        await _cleanup(uid)


# ── list_reversible ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_reversible_excludes_reverted(db_ready, journal_on, stub_drive):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        listed = await js.list_reversible(uid)
        assert [r["id"] for r in listed] == [rid]
        await js.undo(rid, uid)
        assert await js.list_reversible(uid) == []        # plus annulable
    finally:
        await _cleanup(uid)


# ── L'opération inverse Drive réelle (trashed=False) ─────────────────────


@pytest.mark.asyncio
async def test_drive_untrash_sets_trashed_false(monkeypatch):
    captured: dict = {}

    class _FakeFiles:
        def update(self, **kw):
            captured.update(kw)
            return self

        def execute(self):
            return {}

    class _FakeService:
        def files(self):
            return _FakeFiles()

    async def fake_creds(user_id):
        return "{creds}"

    async def fake_service(creds):
        return _FakeService()

    monkeypatch.setattr(creg, "_creds_for_user", fake_creds)
    monkeypatch.setattr("app.agent.tools.drive_tool._get_drive_service", fake_service)

    await creg._drive_untrash({"file_id": "F42"}, "u1")
    assert captured["fileId"] == "F42"
    assert captured["body"] == {"trashed": False}


@pytest.mark.asyncio
async def test_drive_untrash_requires_file_id(monkeypatch):
    with pytest.raises(ValueError):
        await creg._drive_untrash({}, "u1")
