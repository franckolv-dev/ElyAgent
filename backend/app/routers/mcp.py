# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ #
# Endpoints                                                            #
# ------------------------------------------------------------------ #

@router.get("/mcp/servers", response_model=list[MCPServerOut])
async def list_mcp_servers(_=Depends(require_admin)):
    async with async_session() as db:
        result = await db.execute(select(MCPServer).order_by(MCPServer.name))
        return result.scalars().all()


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

    return srv


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

    return srv


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
    mgr = get_mcp_client_manager()
    await mgr.unload_server(srv.slug)
    try:
        await mgr.load_server(srv)
        return {"status": "reloaded", "tools": [t.name for t in srv.tools if hasattr(srv, "tools")]}
    except Exception as exc:
        raise HTTPException(500, f"Rechargement échoué : {exc}")
