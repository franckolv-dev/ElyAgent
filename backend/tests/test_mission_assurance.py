import json
import pytest
from datetime import datetime, timezone, timedelta
from tests.test_patch_service import _db, _seed_user, _fake_admin
from app.database import async_session
from app.services import mission_service
from app.services.mission_assurance import (
    reserve,
    finish,
    verify,
    guard_completion,
    suspend,
    resume_connected,
    preflight,
    Check,
)
from app.models.mission import Mission
from app.models.autonomy import MissionAssurance, ActionReceipt


async def mission(checks=None):
    uid = await _seed_user()
    m = await mission_service.create_mission(uid, "Test", "Objectif test", checks=checks)
    await mission_service.start_mission(m.id)
    return m


@pytest.mark.asyncio
async def test_reserved_write_survives_restart_and_needs_review():
    m = await mission()
    rid, old = await reserve(m.id, m.user_id, "gmail_send_email", {"to": "a@example.test", "body": "abc"})
    assert old is None
    again, old = await reserve(m.id, m.user_id, "gmail_send_email", {"body": "abc", "to": "a@example.test"})
    assert again is None and old["status"] == "started"
    ok, results = await verify(m.id, "Tout est fait")
    assert not ok and results[0]["kind"] == "uncertain_action"
    with pytest.raises(ValueError):
        await guard_completion(m.id, "Terminé")
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "waiting_user"
    await finish(rid, True, "Gmail a accepté le message id=123")
    assert (await verify(m.id, "Terminé"))[0]
    assert (await reserve(m.id, m.user_id, "gmail_send_email", {"to": "a@example.test", "body": "abc"}))[1][
        "status"
    ] == "success"


@pytest.mark.asyncio
async def test_explicit_success_requires_receipt_and_bounds_correction():
    m = await mission([{"kind": "tool_success", "value": "calendar_create_event", "count": 1}])
    with pytest.raises(ValueError):
        await mission_service.complete_mission(m.id, "J’ai créé le rendez-vous")
    async with async_session() as db:
        a = await db.get(MissionAssurance, m.id)
        assert a.retries == 1
        assert not json.loads(a.results_json)[0]["passed"]
        assert (await db.get(Mission, m.id)).status == "running"
    with pytest.raises(ValueError):
        await mission_service.complete_mission(m.id, "C’est fait")
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "waiting_user"
    rid, _ = await reserve(m.id, m.user_id, "calendar_create_event", {"summary": "Test"})
    await finish(rid, True, "Créé id=event1")
    assert (await verify(m.id, "Créé"))[0]


@pytest.mark.asyncio
async def test_sources_must_be_returned_and_cited():
    m = await mission([{"kind": "source_count", "count": 2}])
    rid, _ = await reserve(m.id, m.user_id, "web_search", {"query": "demo"})
    await finish(rid, True, "https://a.test/info https://b.test/info")
    assert not (await verify(m.id, "https://invented.test https://a.test/info"))[0]
    assert (await verify(m.id, "https://b.test/info https://a.test/info"))[0]


@pytest.mark.asyncio
async def test_recovery_reconnect_and_expiration(monkeypatch):
    import app.services.mission_assurance as svc

    m = await mission()
    await suspend(m.id, "chrome", "Reconnecte Chrome")
    monkeypatch.setattr(svc, "connected", lambda *_: False)
    await resume_connected()
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "paused"
    monkeypatch.setattr(svc, "connected", lambda *_: True)
    await resume_connected()
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "planning"
    await suspend(m.id, "chrome", "Reconnecte Chrome")
    async with async_session() as db:
        a = await db.get(MissionAssurance, m.id)
        a.waiting_since = datetime.now(timezone.utc) - timedelta(hours=25)
        await db.commit()
    await resume_connected()
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "waiting_user"


@pytest.mark.asyncio
async def test_manual_pause_not_resumed(monkeypatch):
    import app.services.mission_assurance as svc

    m = await mission()
    await mission_service.pause_mission(m.id)
    monkeypatch.setattr(svc, "connected", lambda *_: True)
    await resume_connected()
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "paused"


@pytest.mark.asyncio
async def test_resolution_owned_and_never_fakes_tool_success():
    from app.routers.autonomy import resolve_receipt, Resolve
    from fastapi import HTTPException

    m = await mission()
    rid, _ = await reserve(m.id, m.user_id, "gmail_send_email", {"x": 1})
    await suspend(m.id, "uncertain_action", "Vérifier")
    with pytest.raises(HTTPException):
        await resolve_receipt(rid, Resolve(decision="done", note="Vu dans Gmail"), _fake_admin("other"))
    await resolve_receipt(rid, Resolve(decision="done", note="Vu dans Gmail"), _fake_admin(m.user_id))
    assert (await reserve(m.id, m.user_id, "gmail_send_email", {"x": 1}))[1]["status"] == "human_confirmed"


@pytest.mark.asyncio
async def test_read_is_not_deduplicated():
    m = await mission()
    a, _ = await reserve(m.id, m.user_id, "web_search", {"q": "weather"})
    b, _ = await reserve(m.id, m.user_id, "web_search", {"q": "weather"})
    assert a != b


def test_no_empty_criteria():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Check(kind="response_contains", value="  ")


@pytest.mark.asyncio
async def test_restart_does_not_reuse_previous_run_evidence():
    from app.routers.missions import restart, _RestartBody

    m = await mission([{"kind": "tool_success", "value": "gmail_send_email", "count": 1}])
    rid, _ = await reserve(m.id, m.user_id, "gmail_send_email", {"body": "message"})
    await finish(rid, True, "Message accepté")
    await mission_service.pause_mission(m.id)
    await restart(m.id, _RestartBody(), _fake_admin(m.user_id))
    await mission_service.start_mission(m.id)
    assert not (await verify(m.id, "Le message est parti"))[0]
    new, old = await reserve(m.id, m.user_id, "gmail_send_email", {"body": "message"})
    assert new != rid and old is None


@pytest.mark.asyncio
async def test_restart_refuses_uncertain_action():
    from app.routers.missions import restart, _RestartBody
    from fastapi import HTTPException

    m = await mission()
    await reserve(m.id, m.user_id, "gmail_send_email", {"body": "message"})
    await suspend(m.id, "uncertain_action", "À vérifier")
    with pytest.raises(HTTPException) as error:
        await restart(m.id, _RestartBody(), _fake_admin(m.user_id))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_failed_write_pauses_immediately():
    m = await mission()
    rid, _ = await reserve(m.id, m.user_id, "desktop_write_file", {"path": "/example"})
    await finish(rid, False, "Délai dépassé")
    async with async_session() as db:
        assert (await db.get(Mission, m.id)).status == "waiting_user"
