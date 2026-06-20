# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_acl.py
# @brief      J4 — ACL MCP : isolation multi-user, admin instance, risque→HITL.
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.mcp_acl import check_mcp_tool_access


async def _ensure_user(uid: str, role: str = "user") -> str:
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        if await db.get(User, uid) is None:
            db.add(User(id=uid, username=uid, email=f"{uid}@test.local",
                        hashed_password="x", role=role))
            await db.commit()
    return uid


@pytest_asyncio.fixture
async def make_server():
    """Factory : crée un MCPServer + un MCPTool, renvoie (server, tool).
    Nettoie tout en teardown."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer, MCPTool

    await init_db()
    created: list[str] = []

    async def _make(*, scope, owner=None, trust="active", kill=False,
                    risk="medium", remote="do_thing"):
        if owner:
            await _ensure_user(owner)
        slug = f"acl_{uuid.uuid4().hex[:8]}"
        async with async_session() as db:
            srv = MCPServer(name=slug, slug=slug, transport="streamable_http",
                            url="https://x/mcp", scope=scope, owner_user_id=owner,
                            trust_state=trust, kill_switch=kill, enabled=True)
            db.add(srv)
            await db.commit()
            await db.refresh(srv)
            local = f"mcp__{slug}__{remote}"
            tool = MCPTool(server_id=srv.id, remote_name=remote, local_name=local,
                           risk_level=risk, enabled=False)
            db.add(tool)
            await db.commit()
            created.append(srv.id)
            return srv, local

    yield _make

    from app.database import async_session as _s
    from app.models.mcp_server import MCPServer as _S, MCPTool as _T
    async with _s() as db:
        for sid in created:
            for t in (await db.execute(select(_T).where(_T.server_id == sid))).scalars().all():
                await db.delete(t)
            srv = await db.get(_S, sid)
            if srv:
                await db.delete(srv)
        await db.commit()


@pytest.mark.asyncio
async def test_user_server_owner_allowed(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner)
    d = await check_mcp_tool_access(owner, local, is_admin=False)
    assert d.allowed is True
    assert d.needs_hitl is True   # défaut "ask" → confirmation


@pytest.mark.asyncio
async def test_user_server_other_user_denied_isolation(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    other = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner)
    d = await check_mcp_tool_access(other, local, is_admin=False)
    assert d.allowed is False
    assert "autre utilisateur" in (d.reason or "")


@pytest.mark.asyncio
async def test_instance_server_admin_allowed_user_denied(make_server):
    _srv, local = await make_server(scope="instance")
    admin = await check_mcp_tool_access("admin_user", local, is_admin=True)
    assert admin.allowed is True
    user = await check_mcp_tool_access("plain_user", local, is_admin=False)
    assert user.allowed is False


@pytest.mark.asyncio
async def test_kill_switch_denies(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, kill=True)
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is False
    assert "kill" in (d.reason or "").lower()


@pytest.mark.asyncio
async def test_quarantined_server_denied(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, trust="quarantined")
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is False


@pytest.mark.asyncio
async def test_explicit_allow_skips_hitl(make_server):
    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool, MCPToolPermission
    from sqlalchemy import select

    owner = f"u_{uuid.uuid4().hex[:6]}"
    srv, local = await make_server(scope="user", owner=owner, risk="low")
    async with async_session() as db:
        tool = (await db.execute(select(MCPTool).where(MCPTool.local_name == local))).scalar_one()
        db.add(MCPToolPermission(user_id=owner, server_id=srv.id, tool_id=tool.id, decision="allow"))
        await db.commit()
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is True
    assert d.needs_hitl is False   # "allow" explicite → pas de confirmation


@pytest.mark.asyncio
async def test_unknown_tool_denied():
    d = await check_mcp_tool_access("u", "mcp__nope__ghost")
    assert d.allowed is False
