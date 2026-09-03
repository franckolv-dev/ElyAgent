# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_catalogue.py
# @brief      J3 — classification de risque, persistance catalogue, pagination.
# @license    MIT
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.mcp_catalogue import classify_risk, persist_catalogue
from app.services.mcp_client import _collect_tools


# ─────────────────────────────────────────────────────────────────────────
# Classification de risque
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("delete_file", "critical"),
    ("drop_table", "critical"),
    ("charge_card", "critical"),
    ("send_email", "high"),
    ("create_issue", "high"),
    ("search_docs", "low"),
    ("get_time", "low"),
])
def test_classify_risk_by_name(name, expected):
    assert classify_risk(name, None, None) == expected


def test_classify_risk_sensitive_param_bumps_to_medium():
    # Nom anodin mais paramètre `command` → au moins medium.
    assert classify_risk("frobnicate", "does a thing",
                         {"properties": {"command": {"type": "string"}}}) == "medium"


# ─────────────────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────────────────


class _Page:
    def __init__(self, tools, nextCursor=None):
        self.tools = tools
        self.nextCursor = nextCursor


@pytest.mark.asyncio
async def test_collect_tools_paginates():
    pages = {
        None: _Page(["a", "b"], nextCursor="p2"),
        "p2": _Page(["c"], nextCursor=None),
    }

    async def list_fn(cursor):
        return pages[cursor]

    tools = await _collect_tools(list_fn)
    assert tools == ["a", "b", "c"]


# ─────────────────────────────────────────────────────────────────────────
# Persistance du catalogue
# ─────────────────────────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name, schema=None):
        self.name = name
        self.title = name.title()
        self.description = f"{name} tool"
        self.inputSchema = schema or {"type": "object", "properties": {}}
        self.outputSchema = None
        self.annotations = None


@pytest_asyncio.fixture
async def server_row():
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer, MCPTool

    await init_db()
    slug = f"cat_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        srv = MCPServer(name="Cat", slug=slug, transport="stdio", command="noop", enabled=True)
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        sid = srv.id
    try:
        yield sid, slug
    finally:
        async with async_session() as db:
            for r in (await db.execute(select(MCPTool).where(MCPTool.server_id == sid))).scalars().all():
                await db.delete(r)
            for r in (await db.execute(select(MCPServer).where(MCPServer.id == sid))).scalars().all():
                await db.delete(r)
            await db.commit()


async def _tools_for(server_id):
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPTool

    async with async_session() as db:
        rows = (await db.execute(
            select(MCPTool).where(MCPTool.server_id == server_id)
        )).scalars().all()
        return {r.remote_name: r for r in rows}


@pytest.mark.asyncio
async def test_new_tools_land_quarantined(server_row):
    sid, slug = server_row
    await persist_catalogue(sid, slug, [_FakeTool("search"), _FakeTool("delete_x")])
    rows = await _tools_for(sid)
    assert set(rows) == {"search", "delete_x"}
    # Découvert ≠ activé.
    assert all(r.enabled is False for r in rows.values())
    # Nom local namespacé + risque classé.
    assert rows["search"].local_name == f"mcp__{slug}__search"
    assert rows["delete_x"].risk_level == "critical"


@pytest.mark.asyncio
async def test_changed_definition_requarantines(server_row):
    from app.database import async_session
    from app.models.mcp_server import MCPTool
    from sqlalchemy import select

    sid, slug = server_row
    await persist_catalogue(sid, slug, [_FakeTool("search")])

    # L'admin approuve l'outil (enabled=True).
    async with async_session() as db:
        row = (await db.execute(
            select(MCPTool).where(MCPTool.server_id == sid, MCPTool.remote_name == "search")
        )).scalar_one()
        row.enabled = True
        await db.commit()

    # Le serveur change le schéma de `search` → la définition change.
    changed = _FakeTool("search", schema={"type": "object", "properties": {"q": {"type": "string"}}})
    await persist_catalogue(sid, slug, [changed])

    rows = await _tools_for(sid)
    # Re-quarantaine : l'autorisation ne vaut plus pour la nouvelle définition.
    assert rows["search"].enabled is False


@pytest.mark.asyncio
async def test_removed_tool_is_dropped(server_row):
    sid, slug = server_row
    await persist_catalogue(sid, slug, [_FakeTool("a"), _FakeTool("b")])
    assert set(await _tools_for(sid)) == {"a", "b"}
    # `b` disparaît côté serveur.
    await persist_catalogue(sid, slug, [_FakeTool("a")])
    assert set(await _tools_for(sid)) == {"a"}
