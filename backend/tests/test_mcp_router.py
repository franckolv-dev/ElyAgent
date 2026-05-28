# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_router.py
# @brief      Tests for the /admin/mcp/servers REST router (Sprint 4a J2)
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app/routers/mcp.py`` — direct-handler style (no TestClient).

We register fake skills with ``scopes=["mcp"]`` directly in the registry,
matching what ``MCPClientManager.load_server`` would have produced at
runtime. This avoids spawning a real ``uv tool run`` process inside the
test loop while still exercising the router's enrichment + reload paths
end-to-end through the DB.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _register_fake_mcp_skill(slug: str, tool_names: list[str]) -> None:
    """Drop a ``mcp_<slug>`` skill in the registry. Matches the shape
    produced by ``mcp_client.load_server`` (scopes=['mcp'])."""
    from app.skills.base import Skill
    from app.skills.registry import get_skill_registry

    skill = Skill(
        name=f"mcp_{slug}",
        display_name=f"MCP {slug}",
        description="fake mcp skill",
        icon="🔌",
        scopes=["mcp"],
        tools=[_FakeTool(n) for n in tool_names],
        author="mcp",
    )
    get_skill_registry().register_or_replace(skill)


def _unregister_fake_mcp_skill(slug: str) -> None:
    from app.skills.registry import get_skill_registry

    get_skill_registry().unregister(f"mcp_{slug}")


@pytest_asyncio.fixture
async def fresh_mcp_row():
    """Create one MCPServer DB row + register a matching fake skill.
    Yields (server_id, slug). Cleans up on teardown.

    The fixture also stubs the MCPClientManager so reload/update/delete
    don't try to spawn real uv subprocesses."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer

    await init_db()
    slug = f"mcprtest_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        srv = MCPServer(
            name=f"Test {slug}",
            slug=slug,
            transport="stdio",
            command=f"echo {slug}",
            description="fixture",
            enabled=True,
        )
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        srv_id = srv.id

    _register_fake_mcp_skill(slug, ["t_alpha", "t_beta"])

    try:
        yield srv_id, slug
    finally:
        _unregister_fake_mcp_skill(slug)
        async with async_session() as db:
            for row in (await db.execute(
                select(MCPServer).where(MCPServer.slug == slug)
            )).scalars().all():
                await db.delete(row)
            await db.commit()


@pytest.fixture
def stub_mcp_manager(monkeypatch):
    """Replace MCPClientManager.{load_server, unload_server} with stubs
    that just register/unregister a fake skill. Spawning a real `uv
    tool run` subprocess inside pytest is too slow and adds flakiness."""
    from app.services import mcp_client

    async def fake_load_server(self, srv):
        _register_fake_mcp_skill(srv.slug, ["t_alpha", "t_beta"])

    async def fake_unload_server(self, slug):
        _unregister_fake_mcp_skill(slug)

    monkeypatch.setattr(mcp_client.MCPClientManager, "load_server", fake_load_server)
    monkeypatch.setattr(mcp_client.MCPClientManager, "unload_server", fake_unload_server)


# ─────────────────────────────────────────────────────────────────────────
# _decorate_with_runtime — unit
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decorate_returns_enriched_shape(fresh_mcp_row):
    """`_decorate_with_runtime` must merge DB row + live registry into
    the response model with tool_count + tool_names set."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import _decorate_with_runtime

    srv_id, slug = fresh_mcp_row
    async with async_session() as db:
        srv = (await db.execute(select(MCPServer).where(MCPServer.id == srv_id))).scalar_one()

    out = _decorate_with_runtime(srv)
    assert out.id == srv_id
    assert out.slug == slug
    assert out.tool_count == 2
    assert sorted(out.tool_names or []) == ["t_alpha", "t_beta"]


def test_decorate_returns_none_count_when_skill_absent():
    """If no `mcp_<slug>` skill is registered (server disabled or just
    failed to load), tool_count + tool_names must be None — NOT empty
    list — so the UI can distinguish "disabled" from "loaded but 0 tools"."""
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import _decorate_with_runtime

    srv = MCPServer(
        id="x",
        name="orphan",
        slug=f"orphan_{uuid.uuid4().hex[:6]}",
        transport="stdio",
        command="noop",
        enabled=False,
    )
    out = _decorate_with_runtime(srv)
    assert out.tool_count is None
    assert out.tool_names is None


# ─────────────────────────────────────────────────────────────────────────
# Router endpoints — direct handler call
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_servers_returns_enriched_payload(fresh_mcp_row):
    """GET /admin/mcp/servers must return the enriched MCPServerOut
    shape including tool_count + tool_names."""
    from app.routers.mcp import list_mcp_servers

    srv_id, slug = fresh_mcp_row
    rows = await list_mcp_servers(_=None)

    found = [r for r in rows if r.slug == slug]
    assert len(found) == 1
    assert found[0].tool_count == 2
    assert sorted(found[0].tool_names or []) == ["t_alpha", "t_beta"]


@pytest.mark.asyncio
async def test_create_server_rejects_duplicate_slug(fresh_mcp_row, stub_mcp_manager):
    """POST /admin/mcp/servers with an existing slug must 400."""
    from fastapi import HTTPException

    from app.routers.mcp import MCPServerCreate, create_mcp_server

    _srv_id, slug = fresh_mcp_row
    body = MCPServerCreate(
        name="dup",
        slug=slug,
        transport="stdio",
        command="echo dup",
        enabled=False,
    )
    with pytest.raises(HTTPException) as exc:
        await create_mcp_server(body, _=None)
    assert exc.value.status_code == 400
    assert "existe déjà" in exc.value.detail


@pytest.mark.asyncio
async def test_create_server_enriches_response(stub_mcp_manager):
    """POST /admin/mcp/servers must return the enriched shape (tool_count
    populated because the stubbed load_server registers a fake skill)."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import MCPServerCreate, create_mcp_server

    slug = f"mcpcrtest_{uuid.uuid4().hex[:8]}"
    body = MCPServerCreate(
        name="created",
        slug=slug,
        transport="stdio",
        command="echo create",
        enabled=True,
    )
    try:
        out = await create_mcp_server(body, _=None)
        assert out.slug == slug
        # Stub registers a skill with 2 fake tools — should surface
        assert out.tool_count == 2
        assert "t_alpha" in (out.tool_names or [])
    finally:
        _unregister_fake_mcp_skill(slug)
        async with async_session() as db:
            for row in (await db.execute(
                select(MCPServer).where(MCPServer.slug == slug)
            )).scalars().all():
                await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_reload_server_returns_actual_tool_names(fresh_mcp_row, stub_mcp_manager):
    """Regression guard for the latent bug we fixed in J2: the reload
    endpoint used to return ``[t.name for t in srv.tools if hasattr(srv,
    "tools")]`` which was always [] because MCPServer (the DB model)
    has no .tools attribute. The fix reads the live skill registry
    after load_server completes."""
    from app.routers.mcp import reload_mcp_server

    srv_id, slug = fresh_mcp_row
    res = await reload_mcp_server(srv_id, _=None)
    assert res["status"] == "reloaded"
    assert sorted(res["tools"]) == ["t_alpha", "t_beta"], (
        "reload must return the actual tool names from the freshly "
        "registered skill — the old `[t.name for t in srv.tools]` "
        "returned [] because the DB model has no .tools attribute"
    )


@pytest.mark.asyncio
async def test_reload_unknown_server_404(stub_mcp_manager):
    """Reloading a non-existent server must 404, not crash."""
    from fastapi import HTTPException

    from app.routers.mcp import reload_mcp_server

    with pytest.raises(HTTPException) as exc:
        await reload_mcp_server("does-not-exist", _=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_server_drops_skill_and_row(fresh_mcp_row, stub_mcp_manager):
    """DELETE must remove both the DB row AND unregister the skill."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import delete_mcp_server
    from app.skills.registry import get_skill_registry

    srv_id, slug = fresh_mcp_row
    # Sanity: skill is registered
    assert get_skill_registry().get_skill(f"mcp_{slug}") is not None

    result = await delete_mcp_server(srv_id, _=None)
    assert result == {"status": "deleted"}

    # Skill gone
    assert get_skill_registry().get_skill(f"mcp_{slug}") is None
    # Row gone
    async with async_session() as db:
        row = (await db.execute(
            select(MCPServer).where(MCPServer.id == srv_id)
        )).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_update_server_renames_slug_and_reloads(fresh_mcp_row, stub_mcp_manager):
    """PUT must close the OLD slug's skill and (re)load under the new
    config. The enriched response reflects the new state."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import MCPServerUpdate, update_mcp_server
    from app.skills.registry import get_skill_registry

    srv_id, old_slug = fresh_mcp_row
    new_name = "renamed-test"
    body = MCPServerUpdate(name=new_name, description="updated", enabled=True)
    out = await update_mcp_server(srv_id, body, _=None)
    assert out.name == new_name
    assert out.description == "updated"
    # Stub re-registers under the same slug → tool_count carries through
    assert out.tool_count == 2

    # DB row updated
    async with async_session() as db:
        row = (await db.execute(
            select(MCPServer).where(MCPServer.id == srv_id)
        )).scalar_one()
        assert row.name == new_name

    # Skill still around (same slug)
    assert get_skill_registry().get_skill(f"mcp_{old_slug}") is not None


@pytest.mark.asyncio
async def test_update_disabled_server_does_not_reload(fresh_mcp_row, stub_mcp_manager):
    """When the admin sets enabled=False via PUT, the skill must be
    removed and NOT re-loaded."""
    from app.routers.mcp import MCPServerUpdate, update_mcp_server
    from app.skills.registry import get_skill_registry

    srv_id, slug = fresh_mcp_row
    body = MCPServerUpdate(enabled=False)
    out = await update_mcp_server(srv_id, body, _=None)
    assert out.enabled is False
    # Skill unregistered
    assert get_skill_registry().get_skill(f"mcp_{slug}") is None
    # And the enriched response surfaces that as None (vs 0)
    assert out.tool_count is None
    assert out.tool_names is None
