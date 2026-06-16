# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_server.py
# @brief      Serveur MCP d'ELY (J2) — tools, middleware d'auth, bout-en-bout.
# =============================================================================
"""Tests du serveur MCP : les 4 tools (unitaires), le middleware d'auth, et un
test bout-en-bout du transport Streamable-HTTP (preuve que la clé API → user_id
se propage jusqu'au tool via le vrai transport).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from starlette.applications import Starlette
from starlette.routing import Mount

from app.database import async_session, init_db
from app.models.api_key import ApiKey
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.routers.api_keys import _generate_plaintext, hash_key
from app.mcp_server import (
    MCP_USER_ID,
    _require_user_id,
    build_mcp_app,
    ely_create_scheduled_task,
    ely_list_scheduled_tasks,
    ely_memory_search,
    mcp,
)


@pytest_asyncio.fixture
async def _user():
    await init_db()
    uid = "mcp_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(ScheduledTask).where(ScheduledTask.user_id == uid))
        await db.execute(delete(ApiKey).where(ApiKey.user_id == uid))
        await db.commit()


async def _mint_key(uid: str) -> str:
    key = _generate_plaintext()
    async with async_session() as db:
        db.add(ApiKey(user_id=uid, name="t", key_hash=hash_key(key),
                      last_4=key[-4:], created_at=datetime.utcnow()))
        await db.commit()
    return key


# ── _require_user_id ─────────────────────────────────────────────────────────
def test_require_user_id_raises_when_unset():
    tok = MCP_USER_ID.set("")
    try:
        with pytest.raises(ValueError):
            _require_user_id()
    finally:
        MCP_USER_ID.reset(tok)


# ── Tools (unitaires, var posée à la main) ───────────────────────────────────
@pytest.mark.asyncio
async def test_memory_search(monkeypatch):
    class _Mgr:
        async def get_relevant_memories(self, q, user_id, lim):
            return [f"fact:{user_id}:{q}"]
    monkeypatch.setattr("app.services.memory_manager.get_memory_manager", lambda: _Mgr())
    tok = MCP_USER_ID.set("user-1")
    try:
        out = await ely_memory_search("rappels", 5)
    finally:
        MCP_USER_ID.reset(tok)
    assert "fact:user-1:rappels" in out


@pytest.mark.asyncio
async def test_memory_search_empty(monkeypatch):
    class _Mgr:
        async def get_relevant_memories(self, q, user_id, lim):
            return []
    monkeypatch.setattr("app.services.memory_manager.get_memory_manager", lambda: _Mgr())
    tok = MCP_USER_ID.set("user-1")
    try:
        out = await ely_memory_search("rien", 5)
    finally:
        MCP_USER_ID.reset(tok)
    assert "Aucun souvenir" in out


@pytest.mark.asyncio
async def test_list_scheduled_tasks(_user):
    async with async_session() as db:
        db.add(ScheduledTask(user_id=_user, name="Daily", prompt="brief",
                             cron_expression="0 8 * * *", channel="web", enabled=True))
        await db.commit()
    tok = MCP_USER_ID.set(_user)
    try:
        out = await ely_list_scheduled_tasks()
    finally:
        MCP_USER_ID.reset(tok)
    assert '"Daily"' in out and '"count": 1' in out


@pytest.mark.asyncio
async def test_create_scheduled_task_valid(_user, monkeypatch):
    monkeypatch.setattr("app.services.scheduler.schedule_task", lambda task: True)
    tok = MCP_USER_ID.set(_user)
    try:
        out = await ely_create_scheduled_task("Rappel", "fais X", "0 9 * * 1")
    finally:
        MCP_USER_ID.reset(tok)
    assert "créée" in out.lower()
    async with async_session() as db:
        rows = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.user_id == _user)
        )).scalars().all()
    assert len(rows) == 1 and rows[0].name == "Rappel"


@pytest.mark.asyncio
async def test_create_scheduled_task_invalid_cron(_user, monkeypatch):
    monkeypatch.setattr("app.services.scheduler.schedule_task", lambda task: False)
    tok = MCP_USER_ID.set(_user)
    try:
        out = await ely_create_scheduled_task("X", "y", "not-a-cron")
    finally:
        MCP_USER_ID.reset(tok)
    assert "invalide" in out.lower()
    async with async_session() as db:
        rows = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.user_id == _user)
        )).scalars().all()
    assert len(rows) == 0  # rien persisté si cron invalide


# ── ely_chat (graphe mocké) ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ely_chat_runs_turn_and_persists(_user, monkeypatch):
    from langchain_core.messages import AIMessage
    from app.models.conversation import Conversation, Message
    from app.mcp_server import ely_chat

    captured = {}

    class _FakeGraph:
        async def ainvoke(self, state, config):
            captured["state"] = state
            return {"messages": [AIMessage(content="Réponse d'ELY")]}

    monkeypatch.setattr("app.agent.graph.build_simple_agent_graph", lambda: _FakeGraph())

    tok = MCP_USER_ID.set(_user)
    try:
        out = await ely_chat("Bonjour", "")
    finally:
        MCP_USER_ID.reset(tok)

    assert "Réponse d'ELY" in out
    assert "[conversation_id=" in out
    # mode autonome-sûr passé au graphe
    assert captured["state"]["automated_task"] is True
    assert captured["state"]["user_id"] == _user
    # exchange persisté (user + assistant)
    async with async_session() as db:
        convs = (await db.execute(
            select(Conversation).where(Conversation.user_id == _user)
        )).scalars().all()
        assert len(convs) == 1
        msgs = (await db.execute(
            select(Message).where(Message.conversation_id == convs[0].id)
        )).scalars().all()
        roles = sorted(m.role for m in msgs)
        assert roles == ["assistant", "user"]
        await db.execute(delete(Message).where(Message.conversation_id == convs[0].id))
        await db.execute(delete(Conversation).where(Conversation.user_id == _user))
        await db.commit()


# ── Middleware d'auth (ASGI) ─────────────────────────────────────────────────
async def _drive_middleware(app, authorization: str | None):
    """Pousse une requête HTTP minimale dans le middleware ; renvoie (status, reached)."""
    reached = {"inner": False, "uid": None}

    async def _inner(scope, receive, send):
        reached["inner"] = True
        reached["uid"] = MCP_USER_ID.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    from app.mcp_server import MCPAuthMiddleware
    mw = MCPAuthMiddleware(_inner)
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {"type": "http", "headers": headers, "method": "POST", "path": "/"}
    sent = []

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(msg):
        sent.append(msg)

    await mw(scope, _receive, _send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, reached


@pytest.mark.asyncio
async def test_middleware_valid_key_sets_user(_user):
    key = await _mint_key(_user)
    status, reached = await _drive_middleware(None, f"Bearer {key}")
    assert status == 200
    assert reached["inner"] is True
    assert reached["uid"] == _user


@pytest.mark.asyncio
async def test_middleware_missing_key_401(_user):
    status, reached = await _drive_middleware(None, None)
    assert status == 401
    assert reached["inner"] is False


@pytest.mark.asyncio
async def test_middleware_bad_key_401(_user):
    status, reached = await _drive_middleware(None, "Bearer ely_api_nope")
    assert status == 401
    assert reached["inner"] is False


# ── Bout-en-bout : vrai transport Streamable-HTTP + propagation user_id ───────
@pytest.mark.asyncio
async def test_end_to_end_transport_and_propagation(_user, monkeypatch):
    """La clé API → user_id se propage jusqu'au tool via le vrai transport."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    key = await _mint_key(_user)

    class _Mgr:
        async def get_relevant_memories(self, q, user_id, lim):
            return [f"AUTHED_AS={user_id}"]
    monkeypatch.setattr("app.services.memory_manager.get_memory_manager", lambda: _Mgr())

    parent = Starlette(routes=[Mount("/api/mcp", app=build_mcp_app())])

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=parent),
            base_url="http://testserver", headers=headers, timeout=timeout,
        )

    async with mcp.session_manager.run():
        async with streamablehttp_client(
            "http://testserver/api/mcp/",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=factory,
        ) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                assert "ely_chat" in {t.name for t in tools.tools}
                res = await s.call_tool("ely_memory_search", {"query": "x"})
                assert f"AUTHED_AS={_user}" in res.content[0].text

        # Clé invalide → rejetée (le client lève sur l'initialize 401).
        with pytest.raises(Exception):
            async with streamablehttp_client(
                "http://testserver/api/mcp/",
                headers={"Authorization": "Bearer ely_api_bad"},
                httpx_client_factory=factory,
            ) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
