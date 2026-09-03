# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_acl.py
# @brief      ACL des outils MCP — propriété, permissions, risque → HITL.
# @license    MIT
# =============================================================================
"""Contrôle d'accès par (utilisateur, serveur, outil) — fail-closed.

Remplace la règle « tout MCP = admin » (B-12) par une ACL fine :

* **isolation multi-utilisateur** : un serveur ``scope=user`` n'est utilisable
  que par son propriétaire ;
* **serveur d'instance** : réservé à l'admin par défaut, sauf permission
  explicite ;
* **permission** par (user, serveur, outil) : ``deny|ask|allow_task|allow`` ;
* **risque → HITL** : un outil ``high``/``critical`` confirme par défaut.

En cas de doute (catalogue absent, serveur inactif), on refuse — ou on retombe
sur l'ancien comportement admin-only pour ne jamais ouvrir par accident.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class AclDecision(NamedTuple):
    allowed: bool
    needs_hitl: bool
    reason: str | None
    risk: str


def _deny(reason: str) -> AclDecision:
    return AclDecision(False, False, reason, "medium")


async def _resolve(local_name: str):
    """local_name → (MCPTool, MCPServer) ou (None, None)."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool

    async with async_session() as db:
        tool = (await db.execute(
            select(MCPTool).where(MCPTool.local_name == local_name)
        )).scalar_one_or_none()
        if tool is None:
            return None, None
        server = (await db.execute(
            select(MCPServer).where(MCPServer.id == tool.server_id)
        )).scalar_one_or_none()
        return tool, server


async def _lookup_permission(user_id: str, server_id: str, tool_id: str):
    """Permission la plus spécifique : (outil) puis (serveur entier)."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.mcp_server import MCPToolPermission

    async with async_session() as db:
        rows = (await db.execute(
            select(MCPToolPermission).where(
                MCPToolPermission.user_id == user_id,
                MCPToolPermission.server_id == server_id,
            )
        )).scalars().all()
    tool_rule = next((r for r in rows if r.tool_id == tool_id), None)
    if tool_rule is not None:
        return tool_rule
    return next((r for r in rows if r.tool_id is None), None)


async def check_mcp_tool_access(
    user_id: str, local_name: str, *, is_admin: bool = False,
) -> AclDecision:
    """Décision d'accès pour ``user_id`` sur l'outil MCP ``local_name``."""
    if not user_id:
        return _deny("identité utilisateur manquante")

    tool, server = await _resolve(local_name)

    if server is None:
        # Catalogue absent (persistance ratée, vieille install) → on retombe
        # sur l'ancien filet : outil MCP chargé = ressource d'instance admin.
        try:
            from app.services.mcp_client import mcp_tool_names
            if local_name in mcp_tool_names():
                if is_admin:
                    return AclDecision(True, True, None, "medium")
                return _deny("serveur MCP d'instance réservé à l'administrateur")
        except Exception:
            pass
        return _deny("outil MCP inconnu")

    if getattr(server, "kill_switch", False):
        return _deny("serveur MCP désactivé (kill switch)")
    if (getattr(server, "trust_state", "active") or "active") != "active":
        return _deny("serveur MCP non approuvé")

    scope = getattr(server, "scope", "instance") or "instance"
    perm = await _lookup_permission(user_id, server.id, tool.id)

    if scope == "user":
        # Isolation : seul le propriétaire utilise son serveur personnel.
        if getattr(server, "owner_user_id", None) != user_id:
            return _deny("serveur MCP personnel d'un autre utilisateur")
    else:  # instance
        if not is_admin and (perm is None or perm.decision == "deny"):
            return _deny("serveur MCP d'instance réservé à l'administrateur")

    explicit = perm.decision if perm is not None else None
    if explicit == "deny":
        return _deny("accès refusé par une règle d'autorisation")

    risk = getattr(tool, "risk_level", "medium") or "medium"
    # « Consultation » = lecture seule (annotation readOnlyHint) OU risque local
    # « low », et JAMAIS un outil dont le nom évoque une action dangereuse
    # (high/critical). Une consultation ne modifie rien chez Ely → pas de HITL
    # par défaut (demande Franck 2026-06-20 : valider 10× pour lire des données
    # publiques n'avait aucun intérêt). Le garde des données SORTANTES
    # (secrets/PII) reste appliqué à l'exécution, indépendamment du HITL.
    consultation = (risk not in ("high", "critical")) and (
        _read_only_hint(tool) or risk == "low"
    )
    if explicit in ("allow", "allow_task"):
        needs_hitl = False
    elif risk in ("high", "critical"):
        needs_hitl = True                 # action sensible → toujours confirmer
    elif consultation:
        needs_hitl = False                # lecture → aucune friction
    else:
        needs_hitl = True                 # medium « écriture » sans règle → confirmer
    return AclDecision(True, needs_hitl, None, risk)


def _read_only_hint(tool) -> bool:
    """True si l'outil déclare ``annotations.readOnlyHint == true``.

    Indice fourni par le SERVEUR — non fiable seul (un serveur peut mentir).
    N'est consulté qu'APRÈS avoir écarté les outils localement classés
    high/critical : il ne peut donc JAMAIS rétrograder un outil dangereux,
    seulement éviter le HITL sur une vraie lecture (cf. tool poisoning).
    """
    raw = getattr(tool, "annotations_json", None)
    if not raw:
        return False
    try:
        import json
        ann = json.loads(raw) if isinstance(raw, str) else raw
        return bool(isinstance(ann, dict) and ann.get("readOnlyHint") is True)
    except Exception:
        return False


async def set_permission(user_id: str, local_name: str, decision: str = "allow") -> bool:
    """Persiste une règle d'autorisation MCP par (user, serveur, outil).

    Backe « Toujours autoriser » côté HITL pour les outils MCP : écrit dans
    ``mcp_tool_permissions`` — et NON dans ``hitl_preferences``, que le gate MCP
    ne lit pas (c'était le bug : « Toujours autoriser » ne persistait jamais).
    Never raises — renvoie False en cas d'échec.
    """
    if not user_id or not local_name:
        return False
    tool, server = await _resolve(local_name)
    if tool is None or server is None:
        return False
    try:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.mcp_server import MCPToolPermission

        async with async_session() as db:
            existing = (await db.execute(
                select(MCPToolPermission).where(
                    MCPToolPermission.user_id == user_id,
                    MCPToolPermission.server_id == server.id,
                    MCPToolPermission.tool_id == tool.id,
                )
            )).scalar_one_or_none()
            if existing is not None:
                existing.decision = decision
            else:
                db.add(MCPToolPermission(
                    user_id=user_id, server_id=server.id, tool_id=tool.id,
                    decision=decision, granted_by=user_id,
                ))
            await db.commit()
        return True
    except Exception as exc:
        logger.warning(
            "set_permission MCP a échoué pour %s/%s: %s", user_id[:8], local_name, exc,
        )
        return False


async def _resolve_admin(user_id: str, is_admin: bool | None) -> bool:
    if is_admin is not None:
        return is_admin
    try:
        from app.services.tool_acl import _is_admin
        return await _is_admin(user_id)
    except Exception:
        return False


async def deny_reason(user_id: str, local_name: str, *, is_admin: bool | None = None) -> str | None:
    """None si autorisé, sinon le message de refus (pour tool_acl)."""
    admin = await _resolve_admin(user_id, is_admin)
    decision = await check_mcp_tool_access(user_id, local_name, is_admin=admin)
    return None if decision.allowed else decision.reason


async def needs_hitl(user_id: str, local_name: str, *, is_admin: bool | None = None) -> bool:
    """True si l'appel doit passer par HITL (pour tool_node)."""
    admin = await _resolve_admin(user_id, is_admin)
    decision = await check_mcp_tool_access(user_id, local_name, is_admin=admin)
    return decision.allowed and decision.needs_hitl
