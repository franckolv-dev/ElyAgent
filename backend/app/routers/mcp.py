# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/mcp.py
# @brief      MCP Servers management API (admin only)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""MCP Servers management API (admin only).

GET    /mcp/servers          — list all configured MCP servers
POST   /mcp/servers          — add a new MCP server
PUT    /mcp/servers/{id}     — update an existing MCP server
DELETE /mcp/servers/{id}     — delete a MCP server
POST   /mcp/servers/{id}/reload — reload tools from a running server
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import require_admin
from app.database import async_session
from app.models.mcp_server import MCPServer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mcp"])


# ------------------------------------------------------------------ #
# Schemas                                                              #
# ------------------------------------------------------------------ #

class MCPServerCreate(BaseModel):
    name: str
    slug: str
    transport: str = "stdio"
    command: Optional[str] = None
    url: Optional[str] = None
    env_json: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    url: Optional[str] = None
    env_json: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class MCPServerOut(BaseModel):
    id: str
    name: str
    slug: str
    transport: str
    command: Optional[str]
    url: Optional[str]
    env_json: Optional[str]
    description: Optional[str]
    enabled: bool
    # Live-state fields filled by the list endpoint (not stored in DB).
    # None = unknown (skill not in registry, e.g. enabled=False).
    tool_count: Optional[int] = None
    tool_names: Optional[list[str]] = None

    model_config = {"from_attributes": True}


def _decorate_with_runtime(srv: MCPServer) -> MCPServerOut:
    """Build the response model by merging DB row + live skill registry."""
    from app.skills.registry import get_skill_registry

    skill = get_skill_registry().get_skill(f"mcp_{srv.slug}")
    out = MCPServerOut.model_validate(srv)
    if skill is not None:
        out.tool_count = len(skill.tools)
        out.tool_names = [t.name for t in skill.tools]
    return out


# ------------------------------------------------------------------ #
# Endpoints                                                            #
# ------------------------------------------------------------------ #

@router.get("/mcp/servers", response_model=list[MCPServerOut])
async def list_mcp_servers(_=Depends(require_admin)):
    async with async_session() as db:
        result = await db.execute(select(MCPServer).order_by(MCPServer.name))
        rows = result.scalars().all()
    return [_decorate_with_runtime(s) for s in rows]


@router.post("/mcp/servers", response_model=MCPServerOut)
async def create_mcp_server(body: MCPServerCreate, _=Depends(require_admin)):
    # Validate slug uniqueness
    async with async_session() as db:
        existing = await db.execute(
            select(MCPServer).where(MCPServer.slug == body.slug)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, f"Un serveur MCP avec le slug '{body.slug}' existe déjà.")

        srv = MCPServer(**body.model_dump())
        db.add(srv)
        await db.commit()
        await db.refresh(srv)

    # Attempt to load the server immediately
    if srv.enabled:
        from app.services.mcp_client import get_mcp_client_manager
        try:
            await get_mcp_client_manager().load_server(srv)
        except Exception as exc:
            logger.warning("MCP server created but tools failed to load: %s", exc)

    return _decorate_with_runtime(srv)


@router.put("/mcp/servers/{server_id}", response_model=MCPServerOut)
async def update_mcp_server(server_id: str, body: MCPServerUpdate, _=Depends(require_admin)):
    async with async_session() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        srv = result.scalar_one_or_none()
        if not srv:
            raise HTTPException(404, "Serveur MCP introuvable.")

        old_slug = srv.slug
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(srv, field, value)
        await db.commit()
        await db.refresh(srv)

    # Reload skill in registry
    from app.services.mcp_client import get_mcp_client_manager
    mgr = get_mcp_client_manager()
    await mgr.unload_server(old_slug)
    if srv.enabled:
        try:
            await mgr.load_server(srv)
        except Exception as exc:
            logger.warning("MCP reload failed after update: %s", exc)

    return _decorate_with_runtime(srv)


@router.delete("/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str, _=Depends(require_admin)):
    async with async_session() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        srv = result.scalar_one_or_none()
        if not srv:
            raise HTTPException(404, "Serveur MCP introuvable.")
        slug = srv.slug
        await db.delete(srv)
        await db.commit()

    from app.services.mcp_client import get_mcp_client_manager
    await get_mcp_client_manager().unload_server(slug)
    return {"status": "deleted"}


@router.post("/mcp/servers/{server_id}/reload")
async def reload_mcp_server(server_id: str, _=Depends(require_admin)):
    """Force un rechargement des outils depuis le serveur MCP."""
    async with async_session() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        srv = result.scalar_one_or_none()
        if not srv:
            raise HTTPException(404, "Serveur MCP introuvable.")

    from app.services.mcp_client import get_mcp_client_manager
    from app.skills.registry import get_skill_registry

    mgr = get_mcp_client_manager()
    await mgr.unload_server(srv.slug)
    try:
        await mgr.load_server(srv)
        # Read the freshly-registered skill from the registry — the DB row
        # itself has no `.tools` attribute; tools live on the Skill object
        # mcp_client built. Returning [] silently was a UX trap.
        skill = get_skill_registry().get_skill(f"mcp_{srv.slug}")
        tool_names = [t.name for t in skill.tools] if skill else []
        return {"status": "reloaded", "tools": tool_names}
    except Exception as exc:
        raise HTTPException(500, f"Rechargement échoué : {exc}")
