# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/mcp.py
# @brief      MCP Servers management API (admin only)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""MCP Servers management API (admin only).

GET    /mcp/servers          — list all configured MCP servers
POST   /mcp/servers          — add a new MCP server
PUT    /mcp/servers/{id}     — update an existing MCP server
DELETE /mcp/servers/{id}     — delete a MCP server
POST   /mcp/servers/{id}/reload — reload tools from a running server
"""
from __future__ import annotations

import json
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
    args_json: Optional[str] = None
    url: Optional[str] = None
    # env_json est ACCEPTÉ en entrée (nécessaire pour lancer un stdio) mais
    # JAMAIS renvoyé en sortie — cf. MCPServerOut (redaction).
    env_json: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    kill_switch: bool = False


class MCPServerUpdate(BaseModel):
    name: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    args_json: Optional[str] = None
    url: Optional[str] = None
    env_json: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    kill_switch: Optional[bool] = None


class MCPServerOut(BaseModel):
    id: str
    name: str
    slug: str
    transport: str
    command: Optional[str]
    url: Optional[str]
    description: Optional[str]
    enabled: bool
    # ── Redaction des secrets ──────────────────────────────────────────
    # `env_json` porte des secrets → JAMAIS renvoyé. On expose uniquement
    # les NOMS de clés pour que l'UI montre « quelles » variables sont
    # définies, sans jamais divulguer leurs valeurs.
    env_keys: Optional[list[str]] = None
    # ── État de confiance / santé (Lot 0) ──────────────────────────────
    scope: Optional[str] = None
    trust_state: Optional[str] = None
    health_state: Optional[str] = None
    kill_switch: Optional[bool] = None
    # Live-state fields filled by the list endpoint (not stored in DB).
    # None = unknown (skill not in registry, e.g. enabled=False).
    tool_count: Optional[int] = None
    tool_names: Optional[list[str]] = None

    model_config = {"from_attributes": True}


def _env_key_names(env_json: Optional[str]) -> Optional[list[str]]:
    """Noms de clés d'``env_json`` — JAMAIS les valeurs. None si vide/illisible."""
    if not env_json:
        return None
    try:
        parsed = json.loads(env_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        return sorted(str(k) for k in parsed.keys())
    return None


def _decorate_with_runtime(srv: MCPServer) -> MCPServerOut:
    """Build the response model by merging DB row + live skill registry.

    Secret-safe : ``env_json`` n'est jamais sérialisé ; seul ``env_keys``
    (les noms) traverse l'API."""
    from app.skills.registry import get_skill_registry

    out = MCPServerOut.model_validate(srv)
    out.env_keys = _env_key_names(getattr(srv, "env_json", None))
    skill = get_skill_registry().get_skill(f"mcp_{srv.slug}")
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


# ------------------------------------------------------------------ #
# Quarantaine / approbation (J5) — boucle du parcours de consentement #
# ------------------------------------------------------------------ #


@router.post("/mcp/servers/{server_id}/approve", response_model=MCPServerOut)
async def approve_mcp_server(server_id: str, _=Depends(require_admin)):
    """Approuve un serveur en quarantaine (ex. proposé par Ely) : confiance
    active + activation + chargement réel. C'est ICI — et nulle part dans le
    modèle — que s'autorise l'exécution d'un serveur local."""
    async with async_session() as db:
        srv = (await db.execute(select(MCPServer).where(MCPServer.id == server_id))).scalar_one_or_none()
        if not srv:
            raise HTTPException(404, "Serveur MCP introuvable.")
        srv.trust_state = "active"
        srv.enabled = True
        srv.kill_switch = False
        await db.commit()
        await db.refresh(srv)

    from app.services.mcp_client import get_mcp_client_manager
    try:
        await get_mcp_client_manager().load_server(srv)
    except Exception as exc:
        logger.warning("MCP server approved but failed to load: %s", exc)
    return _decorate_with_runtime(srv)


@router.post("/mcp/servers/{server_id}/quarantine", response_model=MCPServerOut)
async def quarantine_mcp_server(server_id: str, _=Depends(require_admin)):
    """Remet un serveur en quarantaine : déchargé, désactivé, non approuvé."""
    async with async_session() as db:
        srv = (await db.execute(select(MCPServer).where(MCPServer.id == server_id))).scalar_one_or_none()
        if not srv:
            raise HTTPException(404, "Serveur MCP introuvable.")
        srv.trust_state = "quarantined"
        srv.enabled = False
        await db.commit()
        await db.refresh(srv)

    from app.services.mcp_client import get_mcp_client_manager
    await get_mcp_client_manager().unload_server(srv.slug)
    return _decorate_with_runtime(srv)


class MCPToolOut(BaseModel):
    id: str
    remote_name: str
    local_name: str
    description: Optional[str]
    risk_level: str
    enabled: bool
    model_config = {"from_attributes": True}


@router.get("/mcp/servers/{server_id}/tools", response_model=list[MCPToolOut])
async def list_mcp_server_tools(server_id: str, _=Depends(require_admin)):
    """Catalogue des outils découverts d'un serveur (nom, risque, activation)."""
    from app.models.mcp_server import MCPTool

    async with async_session() as db:
        rows = (await db.execute(
            select(MCPTool).where(MCPTool.server_id == server_id).order_by(MCPTool.remote_name)
        )).scalars().all()
    return [MCPToolOut.model_validate(r) for r in rows]


class MCPToolUpdate(BaseModel):
    enabled: bool


@router.patch("/mcp/servers/{server_id}/tools/{tool_id}", response_model=MCPToolOut)
async def update_mcp_tool(server_id: str, tool_id: str, body: MCPToolUpdate, _=Depends(require_admin)):
    """Active/désactive un outil du catalogue (découvert ≠ activé)."""
    from app.models.mcp_server import MCPTool

    async with async_session() as db:
        row = (await db.execute(
            select(MCPTool).where(MCPTool.id == tool_id, MCPTool.server_id == server_id)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Outil MCP introuvable.")
        row.enabled = body.enabled
        await db.commit()
        await db.refresh(row)
    return MCPToolOut.model_validate(row)


class MCPImportBody(BaseModel):
    # Format `mcpServers` (fichier de config standard MCP).
    config: dict


@router.post("/mcp/import")
async def import_mcp_servers(body: MCPImportBody, _=Depends(require_admin)):
    """Importe un fichier ``mcpServers`` : chaque entrée est créée EN QUARANTAINE
    (jamais lancée/activée automatiquement) — l'admin approuve ensuite."""
    import json as _json

    servers = body.config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise HTTPException(400, "Config invalide : clé « mcpServers » (objet) attendue.")

    created: list[str] = []
    async with async_session() as db:
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            slug = _slugify_unique_sync(name, db)
            transport = "streamable_http" if spec.get("url") else "stdio"
            env = spec.get("env")
            srv = MCPServer(
                name=name, slug=slug, transport=transport,
                command=spec.get("command"),
                args_json=_json.dumps(spec["args"]) if isinstance(spec.get("args"), list) else None,
                url=spec.get("url"),
                env_json=_json.dumps(env) if isinstance(env, dict) else None,
                enabled=False, trust_state="quarantined", health_state="unknown",
                scope="instance",
            )
            db.add(srv)
            await db.flush()
            created.append(srv.id)
        await db.commit()
    return {"status": "imported", "count": len(created), "ids": created}


def _slugify_unique_sync(name: str, db) -> str:
    """Slug kebab unique (suffixe court aléatoire pour éviter une 2e requête)."""
    import re
    import uuid as _uuid
    root = re.sub(r"[^a-z0-9]+", "-", (name or "mcp").lower()).strip("-")[:48] or "mcp"
    return f"{root}-{_uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ #
# Registre MCP (J6) — découverte uniquement, zéro confiance implicite #
# ------------------------------------------------------------------ #


class RegistryEntryOut(BaseModel):
    name: str
    description: str
    kind: str
    url: Optional[str]
    command: Optional[str]
    args: list[str]


@router.get("/mcp/registry/search", response_model=list[RegistryEntryOut])
async def search_mcp_registry(q: str, _=Depends(require_admin)):
    """Cherche des serveurs dans le registre MCP officiel. Renvoie des
    SUGGESTIONS — la connexion reste soumise au parcours de consentement."""
    from app.services.mcp_registry import search_registry

    entries = await search_registry(q, limit=10)
    return [
        RegistryEntryOut(
            name=e.name, description=e.description, kind=e.kind,
            url=e.url, command=e.command, args=list(e.args),
        )
        for e in entries
    ]
