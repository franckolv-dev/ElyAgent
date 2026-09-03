# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reversible_j4.py
# @brief      Substrat / J4 — verify + purge + métriques du Reversible Journal.
# @license    MIT
# =============================================================================
from __future__ import annotations

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


def _install_comp(monkeypatch, *, verify="true", revert_ok=True):
    """Installe une compensation stub avec verify contrôlable.

    verify ∈ {"true","false","raise","none"} ; revert_ok=False → revert lève."""
    calls = {"revert": [], "verify": []}

    async def fake_revert(a, u):
        if not revert_ok:
            raise RuntimeError("revert boom")
        calls["revert"].append((dict(a), u))

    fn = None
    if verify != "none":
        async def fake_verify(a, u):
            calls["verify"].append((dict(a), u))
            if verify == "raise":
                raise RuntimeError("verify boom")
            return verify == "true"
        fn = fake_verify

    monkeypatch.setitem(creg._REGISTRY, "restore_from_trash", creg.Compensation(
        name="restore_from_trash",
        capture=lambda args, result: {"file_id": (args or {}).get("file_id")},
        revert=fake_revert, verify=fn,
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


# ── verify câblé dans undo ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_verified_true(db_ready, journal_on, monkeypatch):
    calls = _install_comp(monkeypatch, verify="true")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, uid)
        assert res["ok"] is True and res["verified"] is True
        assert calls["verify"] == [({"file_id": "F1"}, uid)]
        assert (await _get(rid)).status == "reverted"
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_verified_false_still_reverted(db_ready, journal_on, monkeypatch):
    _install_comp(monkeypatch, verify="false")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, uid)
        # revert a réussi mais non confirmé → ok=True, verified=False, statut reverted.
        assert res["ok"] is True and res["verified"] is False
        assert (await _get(rid)).status == "reverted"
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_verify_raises_is_none(db_ready, journal_on, monkeypatch):
    _install_comp(monkeypatch, verify="raise")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, uid)
        assert res["ok"] is True and res["verified"] is None   # la vérif ne casse pas l'undo
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_without_verify_is_none(db_ready, journal_on, monkeypatch):
    _install_comp(monkeypatch, verify="none")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        res = await js.undo(rid, uid)
        assert res["ok"] is True and res["verified"] is None
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_undo_emits_verified_attribute(db_ready, journal_on, monkeypatch):
    _install_comp(monkeypatch, verify="true")
    from app.services.event_envelope import _RING, EventKind
    uid = f"u_{uuid.uuid4().hex}"
    try:
        rid = await js.record_reversible("drive_delete_file", {"file_id": "F1"}, "ok", uid, "fp")
        await js.undo(rid, uid)
        last = _RING[-1]
        assert last.kind is EventKind.COMPENSATION and last.outcome == "reverted"
        assert last.attributes.get("verified") is True
    finally:
        await _cleanup(uid)


# ── Vérification Drive réelle (_drive_is_untrashed) ──────────────────────


def _fake_drive(monkeypatch, trashed_value):
    class _Files:
        def get(self, **kw):
            return self

        def execute(self):
            return {"trashed": trashed_value}

    class _Service:
        def files(self):
            return _Files()

    async def fake_creds(user_id):
        return "{creds}"

    async def fake_service(creds):
        return _Service()

    monkeypatch.setattr(creg, "_creds_for_user", fake_creds)
    monkeypatch.setattr("app.agent.tools.drive_tool._get_drive_service", fake_service)


@pytest.mark.asyncio
async def test_drive_verify_true_when_untrashed(monkeypatch):
    _fake_drive(monkeypatch, trashed_value=False)
    assert await creg._drive_is_untrashed({"file_id": "F1"}, "u1") is True


@pytest.mark.asyncio
async def test_drive_verify_false_when_still_trashed(monkeypatch):
    _fake_drive(monkeypatch, trashed_value=True)
    assert await creg._drive_is_untrashed({"file_id": "F1"}, "u1") is False


@pytest.mark.asyncio
async def test_drive_verify_false_without_file_id(monkeypatch):
    assert await creg._drive_is_untrashed({}, "u1") is False


# ── purge ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_removes_expired_keeps_fresh(db_ready, journal_on, monkeypatch):
    uid = f"u_{uuid.uuid4().hex}"
    try:
        monkeypatch.setattr(js, "_ttl_seconds", lambda: -5)        # déjà expirée
        rid_old = await js.record_reversible("drive_delete_file", {"file_id": "OLD"}, "ok", uid, "fp1")
        monkeypatch.setattr(js, "_ttl_seconds", lambda: 3600)      # fraîche
        rid_new = await js.record_reversible("drive_delete_file", {"file_id": "NEW"}, "ok", uid, "fp2")

        n = await js.purge_expired()
        assert n >= 1
        assert await _get(rid_old) is None        # expirée → purgée
        assert await _get(rid_new) is not None     # fraîche → conservée
    finally:
        await _cleanup(uid)


# ── stats + endpoint admin ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_shape_and_counts(db_ready, journal_on, monkeypatch):
    _install_comp(monkeypatch, verify="none")
    uid = f"u_{uuid.uuid4().hex}"
    try:
        r1 = await js.record_reversible("drive_delete_file", {"file_id": "A"}, "ok", uid, "f1")
        r2 = await js.record_reversible("drive_delete_file", {"file_id": "B"}, "ok", uid, "f2")
        await js.record_reversible("drive_delete_file", {"file_id": "C"}, "ok", uid, "f3")
        await js.undo(r1, uid)
        await js.undo(r2, uid)

        s = await js.stats()
        assert set(s) == {"total", "by_status", "revert_success_rate"}
        assert s["by_status"].get("reverted", 0) >= 2
        assert s["by_status"].get("recorded", 0) >= 1
        assert s["revert_success_rate"] is None or 0.0 <= s["revert_success_rate"] <= 1.0
    finally:
        await _cleanup(uid)


@pytest.mark.asyncio
async def test_admin_stats_endpoint(db_ready, journal_on):
    from app.routers.reversible_actions import reversible_action_stats

    class _Admin:
        id = "admin"

    res = await reversible_action_stats(_=_Admin())
    assert "by_status" in res and "revert_success_rate" in res and "total" in res


def test_admin_stats_route_registered():
    import app.main as main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/admin/reversible-actions/stats" in paths


def test_purge_job_scheduled_id_present():
    # Garde-fou : l'id du job de purge est bien câblé dans main (cron).
    import app.main as main_module
    src = __import__("inspect").getsource(main_module)
    assert "reversible_journal_purge" in src
