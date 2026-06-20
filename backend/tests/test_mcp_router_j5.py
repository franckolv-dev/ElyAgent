# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_router_j5.py
# @brief      J5 — endpoints quarantaine/approbation/catalogue/import.
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_ready():
    from app.database import init_db
    await init_db()


@pytest.fixture
def stub_loader(monkeypatch):
    """Empêche approve de spawner un vrai sous-processus."""
    from app.services import mcp_client

    async def _noop_load(self, srv):
        return None

    async def _noop_unload(self, slug):
        return None

    monkeypatch.setattr(mcp_client.MCPClientManager, "load_server", _noop_load)
    monkeypatch.setattr(mcp_client.MCPClientManager, "unload_server", _noop_unload)


async def _make(*, trust="quarantined", enabled=False, transport="stdio"):
    from app.database import async_session
    from app.models.mcp_server import MCPServer

    slug = f"j5_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        srv = MCPServer(name=slug, slug=slug, transport=transport, command="noop",
                        trust_state=trust, enabled=enabled, scope="instance")
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        return srv.id, slug


@pytest.mark.asyncio
async def test_approve_activates_and_enables(db_ready, stub_loader):
    from app.routers.mcp import approve_mcp_server

    sid, _slug = await _make(trust="quarantined", enabled=False)
    out = await approve_mcp_server(sid, _=None)
    assert out.trust_state == "active"
    assert out.enabled is True


@pytest.mark.asyncio
async def test_quarantine_disables(db_ready, stub_loader):
    from app.routers.mcp import quarantine_mcp_server

    sid, _slug = await _make(trust="active", enabled=True)
    out = await quarantine_mcp_server(sid, _=None)
    assert out.trust_state == "quarantined"
    assert out.enabled is False


@pytest.mark.asyncio
async def test_list_and_toggle_tools(db_ready):
    from app.database import async_session
    from app.models.mcp_server import MCPTool
    from app.routers.mcp import list_mcp_server_tools, update_mcp_tool, MCPToolUpdate

    sid, slug = await _make()
    async with async_session() as db:
        t = MCPTool(server_id=sid, remote_name="run", local_name=f"mcp__{slug}__run",
                    risk_level="high", enabled=False)
        db.add(t)
        await db.commit()
        await db.refresh(t)
        tid = t.id

    tools = await list_mcp_server_tools(sid, _=None)
    assert len(tools) == 1 and tools[0].risk_level == "high" and tools[0].enabled is False

    updated = await update_mcp_tool(sid, tid, MCPToolUpdate(enabled=True), _=None)
    assert updated.enabled is True


@pytest.mark.asyncio
async def test_import_creates_quarantined_servers(db_ready):
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import import_mcp_servers, MCPImportBody

    cfg = {
        "mcpServers": {
            f"fs_{uuid.uuid4().hex[:6]}": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
            },
            f"remote_{uuid.uuid4().hex[:6]}": {"url": "https://mcp.example.com/mcp"},
        }
    }
    res = await import_mcp_servers(MCPImportBody(config=cfg), _=None)
    assert res["status"] == "imported" and res["count"] == 2

    async with async_session() as db:
        for sid in res["ids"]:
            srv = await db.get(MCPServer, sid)
            assert srv.trust_state == "quarantined"
            assert srv.enabled is False  # jamais activé à l'import


@pytest.mark.asyncio
async def test_import_rejects_bad_config(db_ready):
    from fastapi import HTTPException

    from app.routers.mcp import import_mcp_servers, MCPImportBody

    with pytest.raises(HTTPException) as exc:
        await import_mcp_servers(MCPImportBody(config={"nope": 1}), _=None)
    assert exc.value.status_code == 400
