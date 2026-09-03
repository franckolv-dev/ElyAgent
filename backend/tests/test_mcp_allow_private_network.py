# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_allow_private_network.py
# @brief      Exposition de allow_private_network dans le schéma admin MCP.
# @license    MIT
# =============================================================================
"""L'exception réseau privé/LAN (`allow_private_network`) est réglable via
l'API admin (create/update) et renvoyée par MCPServerOut."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


def test_serverout_exposes_allow_private_network():
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import MCPServerOut

    srv = MCPServer(id="s1", name="LAN", slug="lan", transport="streamable_http",
                    url="https://x/mcp", enabled=True, allow_private_network=True)
    dumped = MCPServerOut.model_validate(srv).model_dump()
    assert dumped["allow_private_network"] is True


@pytest.mark.asyncio
async def test_create_and_update_allow_private_network():
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import MCPServerCreate, MCPServerUpdate, create_mcp_server, update_mcp_server

    slug = f"lan_{uuid.uuid4().hex[:6]}"
    out = await create_mcp_server(
        MCPServerCreate(name="LAN", slug=slug, transport="streamable_http",
                        url="https://x/mcp", enabled=False, allow_private_network=True),
        _=None)
    assert out.allow_private_network is True

    async with async_session() as db:
        srv = (await db.execute(select(MCPServer).where(MCPServer.slug == slug))).scalar_one()
    assert srv.allow_private_network is True

    # Update : on peut le repasser à False.
    out2 = await update_mcp_server(srv.id, MCPServerUpdate(allow_private_network=False), _=None)
    assert out2.allow_private_network is False


@pytest.mark.asyncio
async def test_default_false_when_absent():
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import MCPServerCreate, create_mcp_server

    slug = f"pub_{uuid.uuid4().hex[:6]}"
    await create_mcp_server(
        MCPServerCreate(name="Pub", slug=slug, transport="streamable_http",
                        url="https://x/mcp", enabled=False),
        _=None)
    async with async_session() as db:
        srv = (await db.execute(select(MCPServer).where(MCPServer.slug == slug))).scalar_one()
    # exclude_none ⇒ défaut modèle (False), jamais NULL.
    assert srv.allow_private_network is False
