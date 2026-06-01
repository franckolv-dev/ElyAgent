# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_t_mcp_admin_crud.py
# @brief      Sprint 3.7.3 J4 — structural regression : Sprint 4a MCP admin
#             API layer. create_mcp_server persists + rejects a duplicate slug
#             (HTTP 400) ; list_mcp_servers surfaces it. Complements scenario Q
#             (raw-model round-trip) by exercising the router-level contract.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario T — MCP admin CRUD + slug-uniqueness (router layer)."""
from __future__ import annotations

import uuid


NAME = "T — MCP admin CRUD + slug uniqueness"
DESCRIPTION = (
    "create_mcp_server persists a server (enabled=False → no process spawn), "
    "a second create with the same slug raises HTTP 400, and "
    "list_mcp_servers surfaces it. Router-level contract, complements Q."
)
TAGS = ["shallow"]


async def run() -> dict:
    from fastapi import HTTPException
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import (
        MCPServerCreate,
        create_mcp_server,
        list_mcp_servers,
    )
    from bench.scenarios._base import from_checks

    await init_db()

    slug = f"bench-mcp-crud-{uuid.uuid4().hex[:8]}"
    server_id: str | None = None
    try:
        # enabled=False so create_mcp_server skips load_server (no spawn).
        body = MCPServerCreate(
            name="Bench CRUD Server",
            slug=slug,
            transport="stdio",
            command="uv tool run mcp-server-time",
            description="Synthetic MCP server for the canonical bench.",
            enabled=False,
        )
        created = await create_mcp_server(body)
        server_id = created.id

        # Duplicate slug must be rejected at the API layer.
        dup_rejected = False
        dup_status = None
        try:
            await create_mcp_server(
                MCPServerCreate(name="Dup", slug=slug, enabled=False)
            )
        except HTTPException as exc:
            dup_rejected = True
            dup_status = exc.status_code

        listing = await list_mcp_servers()
        slugs = {s.slug for s in listing}

        checks = {
            "create_returns_id": bool(server_id),
            "create_slug_matches": created.slug == slug,
            "create_not_enabled": created.enabled is False,
            "duplicate_slug_rejected": dup_rejected,
            "duplicate_is_400": dup_status == 400,
            "list_surfaces_server": slug in slugs,
        }
        return from_checks(checks, server_id=server_id, slug=slug)
    finally:
        # mcp_servers has no user_id — clean the row directly (and avoid the
        # update/delete handlers, which call unload_server on a never-loaded
        # slug).
        if server_id is not None:
            async with async_session() as db:
                await db.execute(delete(MCPServer).where(MCPServer.id == server_id))
                await db.commit()
