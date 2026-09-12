import json
import pytest
from sqlalchemy import select
from tests.test_patch_service import _db, _seed_user, _fake_admin
from app.database import async_session
from app.models.autonomy import AutomationRule, AutomationEvent
from app.models.mission import Mission
from app.services.event_automations import enqueue, dispatch_pending, matches
from app.routers.autonomy import create_rule, toggle_rule, preview_rule, RuleInput, Enable, Preview


@pytest.mark.asyncio
async def test_events_are_opt_in_deduplicated_and_bounded():
    uid = await _seed_user()
    user = _fake_admin(uid)
    rule = await create_rule(
        RuleInput(
            name="Factures",
            source="gmail.received",
            goal="Classer les factures",
            sender_contains="compta",
            daily_limit=1,
        ),
        user,
    )
    assert await enqueue(rule["id"], {"sender": "compta"}, "1") is None
    await toggle_rule(rule["id"], Enable(enabled=True), user)
    assert await enqueue(rule["id"], {"sender": "ami"}, "ignore") is None
    first = await enqueue(rule["id"], {"sender": "compta", "text": "é" * 15000}, "1")
    assert first
    assert await enqueue(rule["id"], {"sender": "compta"}, "1") is None
    await enqueue(rule["id"], {"sender": "compta"}, "2")
    await dispatch_pending()
    await dispatch_pending()
    async with async_session() as db:
        missions = (await db.execute(select(Mission).where(Mission.user_id == uid))).scalars().all()
        assert len(missions) == 1
        event = await db.get(AutomationEvent, first)
        assert json.loads(event.payload_json)["text"] == "é" * 4000
        assert missions[0].status == "planning"
    assert (await preview_rule(rule["id"], Preview(sender="compta"), user))["executed"] is False


@pytest.mark.asyncio
async def test_rule_ownership_and_reactivation():
    from fastapi import HTTPException

    uid = await _seed_user()
    other = await _seed_user()
    user = _fake_admin(uid)
    rule = await create_rule(RuleInput(name="Dossier", source="file.indexed", goal="Résumer le document"), user)
    with pytest.raises(HTTPException) as exc:
        await toggle_rule(rule["id"], Enable(enabled=True), _fake_admin(other))
    assert exc.value.status_code == 404
    await toggle_rule(rule["id"], Enable(enabled=True), user)
    eid = await enqueue(rule["id"], {"path": "/docs/test.pdf"}, "doc")
    await toggle_rule(rule["id"], Enable(enabled=False), user)
    await toggle_rule(rule["id"], Enable(enabled=True), user)
    async with async_session() as db:
        assert (await db.get(AutomationEvent, eid)).status == "cancelled"


def test_folder_filter_respects_path_boundaries():
    assert matches({"folder_prefix": "/docs"}, {"path": "/docs/f.pdf"})
    assert not matches({"folder_prefix": "/docs"}, {"path": "/docs-private/f.pdf"})


@pytest.mark.asyncio
async def test_file_poll_uses_ingestion_timestamp_and_durable_id(monkeypatch):
    from app.services.event_automations import poll_files
    from app.services import rag_service
    from datetime import datetime, timezone

    uid = await _seed_user()
    user = _fake_admin(uid)
    r = await create_rule(RuleInput(name="Documents", source="file.indexed", goal="Résumer le document"), user)
    await toggle_rule(r["id"], Enable(enabled=True), user)
    now = datetime.now(timezone.utc).timestamp()

    class Rag:
        async def list_documents(self, user_id, *, created_since):
            assert user_id == uid and created_since <= now
            return [
                {"document_id": "new", "source_file": "/docs/new.txt", "created_at": now, "title": "Nouveau"},
                {"document_id": "old", "created_at": now - 3600, "title": "Ancien"},
            ]

    monkeypatch.setattr(rag_service, "get_rag_service", lambda: Rag())
    async with async_session() as db:
        rule = await db.get(AutomationRule, r["id"])
    await poll_files(rule)
    await poll_files(rule)
    async with async_session() as db:
        rows = (await db.execute(select(AutomationEvent).where(AutomationEvent.rule_id == r["id"]))).scalars().all()
        assert len(rows) == 1 and json.loads(rows[0].payload_json)["document_id"] == "new"


@pytest.mark.asyncio
async def test_gmail_pagination_keeps_window_and_checkpoint(monkeypatch):
    from app.services import event_automations as svc
    from types import SimpleNamespace

    uid = await _seed_user()
    user = _fake_admin(uid)
    r = await create_rule(RuleInput(name="Mail", source="gmail.received", goal="Résumer le mail"), user)
    await toggle_rule(r["id"], Enable(enabled=True), user)
    calls = []

    class API:
        def users(self):
            return self

        def messages(self):
            return self

        def list(self, **kw):
            calls.append(kw)
            return SimpleNamespace(
                execute=lambda: {
                    "messages": [{"id": "m2" if kw.get("pageToken") else "m1"}],
                    **({} if kw.get("pageToken") else {"nextPageToken": "p2"}),
                }
            )

        def get(self, **kw):
            return SimpleNamespace(
                execute=lambda: {
                    "payload": {"headers": [{"name": "From", "value": "a@test"}, {"name": "Subject", "value": "Titre"}]}
                }
            )

    async def google(_):
        return API()

    monkeypatch.setattr(svc, "google_service", google)
    async with async_session() as db:
        rule = await db.get(AutomationRule, r["id"])
    state = await svc.poll_google(rule)
    assert state["page"] == "p2"
    rule.cursor_json = json.dumps(state)
    async with async_session() as db:
        current = await db.get(AutomationRule, r["id"])
        current.cursor_json = rule.cursor_json
        await db.commit()
    next_state = await svc.poll_google(rule)
    assert calls[0]["q"] == calls[1]["q"] and calls[1]["pageToken"] == "p2"
    assert "page" not in next_state and "until" not in next_state
    async with async_session() as db:
        assert (
            len((await db.execute(select(AutomationEvent).where(AutomationEvent.rule_id == r["id"]))).scalars().all())
            == 2
        )


@pytest.mark.asyncio
async def test_reactivation_rejects_old_inflight_poll():
    uid = await _seed_user()
    user = _fake_admin(uid)
    r = await create_rule(RuleInput(name="Mail", source="gmail.received", goal="Résumer le mail"), user)
    await toggle_rule(r["id"], Enable(enabled=True), user)
    async with async_session() as db:
        old = (await db.get(AutomationRule, r["id"])).cursor_json
    await toggle_rule(r["id"], Enable(enabled=False), user)
    await toggle_rule(r["id"], Enable(enabled=True), user)
    assert await enqueue(r["id"], {"sender": "test"}, "stale", expected_cursor=old) is None


def test_folder_filter_normalizes_parent_segments():
    assert not matches({"folder_prefix": "/docs"}, {"path": "/docs/../private/test"})
