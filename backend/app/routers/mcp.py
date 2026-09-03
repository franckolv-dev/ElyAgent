# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/mcp.py
# @brief      MCP Servers management API (admin only)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""MCP Servers management API (admin only).

GET    /mcp/servers          — list all configured MCP servers
POST   /mcp/servers          — add a new MCP server
PUT    /mcp/servers/{id}     — update an existing MCP server
DELETE /mcp/servers/{id}     — delete a MCP server
POST   /mcp/servers/{id}/reload — reload tools from a running server
GET    /mcp/servers/{id}/permissions — list per-user access rules
POST   /mcp/servers/{id}/permissions — grant/deny a user (upsert)
DELETE /mcp/servers/{id}/permissions/{perm_id} — remove a rule
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import require_admin
from app.database import async_session
from app.models.mcp_server import MCPServer
from app.models.user import User

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
    # ── OAuth (J4) — config non secrète. Le secret client / les tokens ne
    # passent JAMAIS par ici (cf. mcp_oauth + Vault). auth_type="oauth2"
    # rend le serveur connectable via le bouton « Se connecter ».
    auth_type: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_scopes: Optional[str] = None
    # ── Sandbox stdio (J5) — config NON secrète. `cwd` = répertoire de travail ;
    # `sandbox_profile_json` = override {mem_bytes, nofile, fsize_bytes}. Lus
    # seulement si `mcp_stdio_sandbox_enabled` est ON.
    cwd: Optional[str] = None
    sandbox_profile_json: Optional[str] = None
    # ── Exception réseau privé/LAN (admin) — désactive la garde SSRF pour CE
    # serveur (cible loopback/LAN/privée autorisée). Opt-in explicite, admin-only.
    allow_private_network: Optional[bool] = None


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
    auth_type: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_scopes: Optional[str] = None
    cwd: Optional[str] = None
    sandbox_profile_json: Optional[str] = None
    allow_private_network: Optional[bool] = None


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
    # ── OAuth (J4) — config NON secrète seulement. `oauth_client_secret_ref`
    # et `oauth_metadata_json` ne sont JAMAIS exposés (secret chiffré / cache
    # backend). L'UI s'en sert pour afficher les boutons « Se connecter ».
    auth_type: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_scopes: Optional[str] = None
    # ── Sandbox stdio (J5) — config NON secrète exposée pour l'admin.
    cwd: Optional[str] = None
    sandbox_profile_json: Optional[str] = None
    # Exception réseau privé/LAN (admin) — cf. schémas d'entrée.
    allow_private_network: Optional[bool] = None
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

        # exclude_none : les Optional non fournis (dont auth_type) retombent sur
        # les défauts du modèle ("none", etc.) — préserve le comportement pré-J4.
        srv = MCPServer(**body.model_dump(exclude_none=True))
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
        # Révocation OAuth (J3) : best-effort, uniquement pour un serveur perso
        # (le Vault est par-utilisateur → on ne peut purger que le propriétaire ;
        # sur un serveur d'instance, chaque utilisateur se déconnecte via
        # DELETE /api/mcp/oauth/{id}). Avant le delete : srv encore lisible.
        if (srv.auth_type or "none") == "oauth2" and (srv.scope or "") == "user" \
                and srv.owner_user_id:
            try:
                from app.services.mcp_credentials import revoke_oauth
                await revoke_oauth(srv.owner_user_id, srv)
            except Exception:  # noqa: BLE001 — ne jamais bloquer la suppression
                logger.warning("Révocation OAuth au delete échouée pour %s", slug)
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


# ------------------------------------------------------------------ #
# Accès utilisateurs — règles mcp_tool_permissions par (user, serveur) #
# ------------------------------------------------------------------ #
# Sur un serveur `scope=instance`, un non-admin est refusé AVANT le HITL
# (mcp_acl.check_mcp_tool_access) : « Toujours autoriser » ne peut donc
# jamais lui écrire de règle. Ces endpoints sont le SEUL moyen pour
# l'admin d'ouvrir un serveur d'instance à un autre utilisateur.
# `tool_id` nul ⇒ règle pour TOUT le serveur. Aucun cache à invalider :
# l'ACL relit la DB à chaque appel.


# Décisions exposées à l'admin. `ask` ouvre l'accès EN gardant le HITL selon
# le risque de l'outil (utile server-wide : autoriser un serveur sans lever la
# confirmation sur ses outils high/critical). `allow_task` (HITL par session)
# n'a pas de sens en pré-attribution admin → non exposé.
_ADMIN_DECISIONS = ("allow", "ask", "deny")


class MCPPermissionCreate(BaseModel):
    user_id: str
    tool_id: Optional[str] = None    # None ⇒ tout le serveur
    # Défaut « ask » (fail-closed, comme le modèle) : ouvre l'accès sans friction
    # sur les outils anodins mais garde la confirmation sur les sensibles.
    decision: str = "ask"            # "allow" | "ask" | "deny"


class MCPPermissionOut(BaseModel):
    id: str
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    server_id: str
    tool_id: Optional[str] = None
    tool_name: Optional[str] = None  # remote_name lisible ; None = tout le serveur
    decision: str
    granted_by: Optional[str] = None
    granted_at: Optional[datetime] = None


async def _get_server_or_404(db, server_id: str) -> MCPServer:
    srv = (await db.execute(
        select(MCPServer).where(MCPServer.id == server_id)
    )).scalar_one_or_none()
    if not srv:
        raise HTTPException(404, "Serveur MCP introuvable.")
    return srv


def _permission_out(perm, user: User | None, tool) -> MCPPermissionOut:
    return MCPPermissionOut(
        id=perm.id, user_id=perm.user_id,
        username=getattr(user, "username", None),
        email=getattr(user, "email", None),
        server_id=perm.server_id, tool_id=perm.tool_id,
        tool_name=getattr(tool, "remote_name", None),
        decision=perm.decision, granted_by=perm.granted_by,
        granted_at=perm.granted_at,
    )


@router.get("/mcp/servers/{server_id}/permissions", response_model=list[MCPPermissionOut])
async def list_mcp_server_permissions(server_id: str, _=Depends(require_admin)):
    """Règles d'accès par utilisateur d'un serveur (server-wide et par outil)."""
    from app.models.mcp_server import MCPTool, MCPToolPermission

    async with async_session() as db:
        await _get_server_or_404(db, server_id)
        perms = (await db.execute(
            select(MCPToolPermission)
            .where(MCPToolPermission.server_id == server_id)
            .order_by(MCPToolPermission.granted_at)
        )).scalars().all()
        users = {u.id: u for u in (await db.execute(
            select(User).where(User.id.in_({p.user_id for p in perms}))
        )).scalars().all()} if perms else {}
        tools = {t.id: t for t in (await db.execute(
            select(MCPTool).where(MCPTool.server_id == server_id)
        )).scalars().all()}
    return [_permission_out(p, users.get(p.user_id), tools.get(p.tool_id)) for p in perms]


@router.post("/mcp/servers/{server_id}/permissions", response_model=MCPPermissionOut)
async def create_mcp_server_permission(
    server_id: str, body: MCPPermissionCreate, admin: User = Depends(require_admin),
):
    """Crée (ou remplace) une règle pour (user, serveur[, outil]) — upsert."""
    from app.models.mcp_server import MCPTool, MCPToolPermission

    if body.decision not in _ADMIN_DECISIONS:
        raise HTTPException(400, "Décision invalide — « allow », « ask » ou « deny » attendu.")

    async with async_session() as db:
        await _get_server_or_404(db, server_id)
        user = (await db.execute(
            select(User).where(User.id == body.user_id)
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(404, "Utilisateur introuvable.")
        tool = None
        if body.tool_id is not None:
            tool = (await db.execute(select(MCPTool).where(
                MCPTool.id == body.tool_id, MCPTool.server_id == server_id,
            ))).scalar_one_or_none()
            if not tool:
                raise HTTPException(404, "Outil MCP introuvable sur ce serveur.")

        # `.first()` (et non scalar_one_or_none) : la table n'a pas de contrainte
        # unique sur (user, server, tool_id) — un doublon accidentel ne doit pas
        # faire échouer l'upsert en 500, on met simplement à jour la 1re ligne.
        existing = (await db.execute(select(MCPToolPermission).where(
            MCPToolPermission.user_id == body.user_id,
            MCPToolPermission.server_id == server_id,
            MCPToolPermission.tool_id == body.tool_id,
        ))).scalars().first()
        if existing is not None:
            existing.decision = body.decision
            existing.granted_by = admin.id
            perm = existing
        else:
            perm = MCPToolPermission(
                user_id=body.user_id, server_id=server_id, tool_id=body.tool_id,
                decision=body.decision, granted_by=admin.id,
            )
            db.add(perm)
        await db.commit()
        await db.refresh(perm)
    return _permission_out(perm, user, tool)


@router.delete("/mcp/servers/{server_id}/permissions/{permission_id}")
async def delete_mcp_server_permission(
    server_id: str, permission_id: str, _=Depends(require_admin),
):
    """Supprime une règle — l'utilisateur retombe sur le défaut (fail-closed)."""
    from app.models.mcp_server import MCPToolPermission

    async with async_session() as db:
        perm = (await db.execute(select(MCPToolPermission).where(
            MCPToolPermission.id == permission_id,
            MCPToolPermission.server_id == server_id,
        ))).scalar_one_or_none()
        if not perm:
            raise HTTPException(404, "Règle d'autorisation introuvable.")
        await db.delete(perm)
        await db.commit()
    return {"status": "deleted"}


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
