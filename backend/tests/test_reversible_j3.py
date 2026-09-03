# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reversible_j3.py
# @brief      Substrat / J3 — compensation par snapshot (rename/move).
# @license    MIT
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
    monkeypatch.setattr(js, "_enabled", lambda: True)


def _install_snapshot_comp(monkeypatch, *, verify="true"):
    """Stub de compensation par snapshot (handle restore_name)."""
    calls = {"revert": [], "snapshot": []}

    async def fake_snapshot(args, uid):
        calls["snapshot"].append((dict(args), uid))
        return {"file_id": (args or {}).get("file_id"), "name": "OLD"}

    async def fake_revert(snap, uid):
        calls["revert"].append((dict(snap), uid))

    fn_v = None
    if verify != "none":
        async def fake_verify(snap, uid):
            return verify == "true"
        fn_v = fake_verify

    monkeypatch.setitem(creg._REGISTRY, "restore_name", creg.Compensation(
        name="restore_name", revert=fake_revert, snapshot=fake_snapshot, verify=fn_v,
    ))
    return calls


async def _cleanup(uid: str):
    from sqlalchemy import delete
    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    async with async_session() as db:
        await db.execute(delete(ReversibleActionRecord).where(ReversibleActionRecord.user_id == uid))
        await db.commit()


async def _get(rid: str):
    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord
    async with async_session() as db:
        return await db.get(ReversibleActionRecord, rid)


# ── Manifeste : capacités réversibles par snapshot ───────────────────────


def test_manifest_overrides_for_snapshot_tools():
    from app.services.capability_manifest import Approval, get_manifest
    rn = get_manifest("drive_rename_file")
    mv = get_manifest("drive_move_file")
    assert rn.compensation == "restore_name"
    assert mv.compensation == "restore_parents"
    # Approbation INCHANGÉE vs dérivation (risk_based) — pas de nouveau HITL.
    assert rn.approval is Approval.RISK_BASED
    assert mv.approval is Approval.RISK_BASED


# ── snapshot_before ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_before_captures_for_snapshot_capability(db_ready, journal_on, monkeypatch):
    calls = _install_snapshot_comp(monkeypatch)
    snap = await js.snapshot_before("drive_rename_file", {"file_id": "F1"}, "u1")
    assert snap == {"file_id": "F1", "name": "OLD"}
    assert calls["snapshot"] == [({"file_id": "F1"}, "u1")]


@pytest.mark.asyncio
async def test_snapshot_before_none_for_inverse_op(db_ready, journal_on):
    # drive_delete_file = restore_from_trash (capture, pas snapshot) → None.
    assert await js.snapshot_before("drive_delete_file", {"file_id": "F1"}, "u1") is None


@pytest.mark.asyncio
async def test_snapshot_before_none_without_compensation(db_ready, journal_on):
    assert await js.snapshot_before("web_search", {"q": "x"}, "u1") is None


@pytest.mark.asyncio
async def test_snapshot_before_none_when_flag_off(db_ready, monkeypatch):
    monkeypatch.setattr(js, "_enabled", lambda: False)
    assert await js.snapshot_before("drive_rename_file", {"file_id": "F1"}, "u1") is None


# ── record_reversible en mode snapshot ───────────────────────────────────


@pytest.mark.asyncio
async def test_record_uses_pre_snapshot(db_ready, journal_on, monkeypatch):
    _install_snapshot_comp(monkeypatch)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible(
            "drive_rename_file", {"file_id": "F1", "new_name": "NEW"}, "ok", uid, "fp",
            pre_snapshot={"file_id": "F1", "name": "OLD"},
        )
        assert rid is not None
        stored = json.loads((await _get(rid)).compensation_args)
        assert stored == {"file_id": "F1", "name": "OLD"}    # l'ÉTAT D'AVANT, pas les args
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_record_no_snapshot_no_entry(db_ready, journal_on, monkeypatch):
    _install_snapshot_comp(monkeypatch)
    uid = f"u_{uuid.uuid4().hex}"
    try:
        # snapshot raté en amont (None) → pas d'entrée (action non annulable).
        rid = await js.record_reversible(
            "drive_rename_file", {"file_id": "F1"}, "ok", uid, "fp", pre_snapshot=None,
        )
        assert rid is None
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_snapshot_capability_restores(db_ready, journal_on, monkeypatch):
    calls = _install_snapshot_comp(monkeypatch, verify="true")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible(
            "drive_rename_file", {"file_id": "F1"}, "ok", uid, "fp",
            pre_snapshot={"file_id": "F1", "name": "OLD"},
        )
        res = await js.undo(rid, uid)
        assert res["ok"] is True and res["verified"] is True
        assert calls["revert"] == [({"file_id": "F1", "name": "OLD"}, uid)]
        assert (await _get(rid)).status == "reverted"
    finally:
        await _cleanup(uid)


# ── Fonctions Drive réelles (snapshot / restore / verify) ────────────────


def _fake_drive(monkeypatch, get_payload):
    """Monkeypatch creg._drive_service → service Drive factice. Renvoie le sink
    des appels update()."""
    sink: list[dict] = []

    class _Files:
        def __init__(self):
            self._op = None

        def get(self, **kw):
            self._op = "get"
            return self

        def update(self, **kw):
            self._op = "update"
            sink.append(kw)
            return self

        def execute(self):
            return get_payload if self._op == "get" else {"id": "x"}

    class _Service:
        def files(self):
            return _Files()

    async def fake_service(user_id):
        return _Service()

    monkeypatch.setattr(creg, "_drive_service", fake_service)
    return sink


@pytest.mark.asyncio
async def test_drive_snapshot_name(monkeypatch):
    _fake_drive(monkeypatch, {"name": "ancien.pdf"})
    snap = await creg._drive_snapshot_name({"file_id": "F1"}, "u1")
    assert snap == {"file_id": "F1", "name": "ancien.pdf"}


@pytest.mark.asyncio
async def test_drive_restore_name_updates(monkeypatch):
    sink = _fake_drive(monkeypatch, {"name": "x"})
    await creg._drive_restore_name({"file_id": "F1", "name": "ancien.pdf"}, "u1")
    assert sink == [{"fileId": "F1", "body": {"name": "ancien.pdf"}}]


@pytest.mark.asyncio
async def test_drive_verify_name(monkeypatch):
    _fake_drive(monkeypatch, {"name": "ancien.pdf"})
    assert await creg._drive_verify_name({"file_id": "F1", "name": "ancien.pdf"}, "u1") is True
    assert await creg._drive_verify_name({"file_id": "F1", "name": "autre.pdf"}, "u1") is False


@pytest.mark.asyncio
async def test_drive_snapshot_parents(monkeypatch):
    _fake_drive(monkeypatch, {"parents": ["P1", "P2"]})
    snap = await creg._drive_snapshot_parents({"file_id": "F1"}, "u1")
    assert snap == {"file_id": "F1", "parents": ["P1", "P2"]}


@pytest.mark.asyncio
async def test_drive_restore_parents_swaps(monkeypatch):
    # get renvoie les parents COURANTS ; restore doit add(old)/remove(courants).
    sink = _fake_drive(monkeypatch, {"parents": ["CUR"]})
    await creg._drive_restore_parents({"file_id": "F1", "parents": ["OLD"]}, "u1")
    assert sink == [{
        "fileId": "F1", "addParents": "OLD", "removeParents": "CUR", "fields": "id,parents",
    }]


@pytest.mark.asyncio
async def test_drive_verify_parents_set_equality(monkeypatch):
    _fake_drive(monkeypatch, {"parents": ["P2", "P1"]})
    assert await creg._drive_verify_parents({"file_id": "F1", "parents": ["P1", "P2"]}, "u1") is True
    assert await creg._drive_verify_parents({"file_id": "F1", "parents": ["P1"]}, "u1") is False
