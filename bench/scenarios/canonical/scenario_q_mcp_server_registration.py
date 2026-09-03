# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_q_mcp_server_registration.py
# @brief      Sprint 3.7.3 J3 — canonical scenario Q : Sprint 4a MCP server
#             registration round-trip at the persistence layer. Create an
#             mcp_servers row, read it back, toggle enabled, and clean up.
#             Does NOT spawn a real MCP process (that's a deep/E2E concern).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario Q — MCP server registration round-trip (DB layer)."""
from __future__ import annotations

import uuid


NAME = "Q — MCP server registration round-trip"
DESCRIPTION = (
    "Persists an mcp_servers row (Sprint 4a), reads it back with its "
    "transport/command/enabled fields intact, toggles enabled off, then "
    "cleans up. Pins the registration contract without connecting a server."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer
    from bench.scenarios._base import from_checks

    await init_db()

    slug = f"bench-mcp-{uuid.uuid4().hex[:8]}"
    server_id: str | None = None
    try:
        async with async_session() as db:
            row = MCPServer(
                name="Bench Time Server",
                slug=slug,
                transport="stdio",
                command="uv tool run mcp-server-time",
                description="Synthetic MCP server for the canonical bench.",
                enabled=True,
            )
            db.add(row)
            await db.commit()
            server_id = row.id

        # Read back — registration round-trip.
        async with async_session() as db:
            fetched = (await db.execute(
                select(MCPServer).where(MCPServer.slug == slug)
            )).scalar_one_or_none()

        round_trip_ok = bool(
            fetched is not None
            and fetched.id == server_id
            and fetched.transport == "stdio"
            and fetched.command == "uv tool run mcp-server-time"
            and fetched.enabled is True
        )

        # Toggle enabled off (admin disable) and confirm it sticks.
        async with async_session() as db:
            srv = (await db.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )).scalar_one()
            srv.enabled = False
            await db.commit()
        async with async_session() as db:
            after = (await db.execute(
                select(MCPServer).where(MCPServer.id == server_id)
            )).scalar_one_or_none()

        checks = {
            "registration_round_trip": round_trip_ok,
            "slug_persisted": fetched is not None and fetched.slug == slug,
            "enabled_toggle_persists": after is not None and after.enabled is False,
        }
        return from_checks(checks, server_id=server_id, slug=slug)
    finally:
        # mcp_servers has no user_id → throwaway_user can't reclaim it.
        if server_id is not None:
            async with async_session() as db:
                await db.execute(delete(MCPServer).where(MCPServer.id == server_id))
                await db.commit()
