# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_model_tools.py
# @brief      J4 — outils model-facing : connect/propose/call (sécurité).
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.skills.builtin import mcp_model_skill as M


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
async def owned():
    """Yield un user_id unique ; nettoie tous ses serveurs MCP en teardown."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer, MCPTool, MCPToolPermission

    await init_db()
    uid = await _ensure_user(f"u_{uuid.uuid4().hex[:8]}")
    yield uid
    async with async_session() as db:
        srvs = (await db.execute(
            select(MCPServer).where(MCPServer.owner_user_id == uid)
        )).scalars().all()
        for s in srvs:
            for t in (await db.execute(select(MCPTool).where(MCPTool.server_id == s.id))).scalars().all():
                await db.delete(t)
            for p in (await db.execute(select(MCPToolPermission).where(MCPToolPermission.server_id == s.id))).scalars().all():
                await db.delete(p)
            await db.delete(s)
        await db.commit()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(M, "_flag_on", lambda: True)


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"{name} desc"
        self.inputSchema = {"type": "object", "properties": {}}
        self.outputSchema = None
        self.title = name
        self.annotations = None


# ─────────────────────────────────────────────────────────────────────────
# Flag
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_off_by_default():
    # Sans flag, les outils renvoient le message désactivé.
    out = await M.mcp_list_servers.coroutine(user_id="u")
    assert "désactivé" in out


# ─────────────────────────────────────────────────────────────────────────
# mcp_connect — garde egress + autonomie remote
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_refuses_non_https(flag_on, owned):
    out = await M.mcp_connect.coroutine(url="http://mcp.example.com/mcp", user_id=owned)
    assert "refusée" in out.lower()


@pytest.mark.asyncio
async def test_connect_refuses_private_target(flag_on, owned):
    out = await M.mcp_connect.coroutine(url="https://10.0.0.1/mcp", user_id=owned)
    assert "refusée" in out.lower()


@pytest.mark.asyncio
async def test_connect_registers_user_scoped_server(flag_on, owned, monkeypatch):
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    import app.services.mcp_egress as egress
    import app.services.mcp_remote as remote

    # Pas de réseau : on neutralise la résolution DNS + on simule le probe.
    monkeypatch.setattr(egress, "validate_egress_url", lambda *a, **k: None)
    monkeypatch.setattr(M, "_hitl", lambda *a, **k: _true())
    async def _fake_probe(url, **k):
        return [_FakeTool("search"), _FakeTool("fetch")]
    monkeypatch.setattr(remote, "probe_remote", _fake_probe)

    out = await M.mcp_connect.coroutine(url="https://mcp.example.com/mcp",
                                        name="Example", user_id=owned)
    assert "Connecté" in out
    async with async_session() as db:
        srv = (await db.execute(
            select(MCPServer).where(MCPServer.owner_user_id == owned)
        )).scalar_one()
        assert srv.scope == "user"
        assert srv.trust_state == "active"
        assert srv.owner_user_id == owned


# ─────────────────────────────────────────────────────────────────────────
# mcp_propose_server — quarantaine, jamais lancé, pas d'auto-approbation
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_server_lands_quarantined_disabled(flag_on, owned):
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer

    out = await M.mcp_propose_server.coroutine(
        name="Local FS", command="npx", args=["-y", "server-filesystem", "/data"],
        user_id=owned,
    )
    assert "QUARANTAINE" in out
    assert "Je ne peux pas" in out  # le modèle ne s'auto-approuve pas
    async with async_session() as db:
        srv = (await db.execute(
            select(MCPServer).where(MCPServer.owner_user_id == owned)
        )).scalar_one()
        assert srv.transport == "stdio"
        assert srv.trust_state == "quarantined"
        assert srv.enabled is False          # NI lancé NI activé


# ─────────────────────────────────────────────────────────────────────────
# mcp_call_tool — politique de données sortantes + isolation
# ─────────────────────────────────────────────────────────────────────────


async def _make_user_server(uid, *, risk="low"):
    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool

    await _ensure_user(uid)
    slug = f"call_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        srv = MCPServer(name=slug, slug=slug, transport="streamable_http",
                        url="https://x/mcp", scope="user", owner_user_id=uid,
                        trust_state="active", enabled=True, auth_type="none")
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        db.add(MCPTool(server_id=srv.id, remote_name="run", local_name=f"mcp__{slug}__run",
                       risk_level=risk, enabled=False))
        await db.commit()
        return srv.id


@pytest.mark.asyncio
async def test_call_tool_blocks_secret_exfiltration(flag_on, owned, monkeypatch):
    # Même autorisé par l'ACL (propriétaire), un secret dans les args est bloqué.
    monkeypatch.setattr(M, "_hitl", lambda *a, **k: _true())
    sid = await _make_user_server(owned)
    out = await M.mcp_call_tool.coroutine(
        server_id=sid, tool_name="run",
        arguments={"token": "ghp_ABCDEFGHIJKLMNOPQRSTUV012345"},
        user_id=owned,
    )
    assert "bloqué" in out.lower()


@pytest.mark.asyncio
async def test_call_tool_denies_other_users_server(flag_on, owned, monkeypatch):
    sid = await _make_user_server(owned)
    other = f"u_{uuid.uuid4().hex[:8]}"
    out = await M.mcp_call_tool.coroutine(
        server_id=sid, tool_name="run", arguments={}, user_id=other,
    )
    assert "introuvable ou non accessible" in out


@pytest.mark.asyncio
async def test_list_servers_isolation(flag_on, owned):
    """Un serveur personnel d'un AUTRE utilisateur ne doit pas apparaître."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool

    other = f"u_{uuid.uuid4().hex[:8]}"
    other_sid = await _make_user_server(other)
    mine_sid = await _make_user_server(owned)
    async with async_session() as db:
        other_slug = (await db.get(MCPServer, other_sid)).slug
        mine_slug = (await db.get(MCPServer, mine_sid)).slug

    out = await M.mcp_list_servers.coroutine(user_id=owned)
    assert mine_slug in out          # mon serveur visible
    assert other_slug not in out     # celui de l'autre, jamais

    async with async_session() as db:
        for t in (await db.execute(select(MCPTool).where(MCPTool.server_id == other_sid))).scalars().all():
            await db.delete(t)
        s = await db.get(MCPServer, other_sid)
        if s:
            await db.delete(s)
        await db.commit()


async def _true():
    return True
