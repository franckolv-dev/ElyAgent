# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tool_acl.py
# @brief      Outils à ressources d'instance réservés au rôle admin
#             (revue multi-utilisateurs 2026-06-10, constat B-12).
# @license    Elastic License 2.0
# =============================================================================
"""Admin-only gate for instance-resource tools.

Les hôtes SSH (``config/hosts.yaml``, clés montées dans le conteneur) et
les serveurs MCP (lancés avec les secrets ``env_json`` posés par l'admin)
sont des ressources d'INSTANCE : avant ce module, tout utilisateur routé
sur le bon domaine pouvait invoquer ces outils **avec l'identité et les
credentials de l'admin**. Acceptable en mono-user, fuite de privilèges en
multi-user.

V1 volontairement simple : ces outils sont réservés au rôle ``admin``.
Une ACL per-user (table + UI, façon ``tool_policy_service`` de la branche
salvage) reste la cible si le besoin émerge.

Le rôle est lu en DB avec un petit cache TTL 60 s — le gate est sur le
chemin chaud de tool_node, pas question d'ajouter une requête par tool
call.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Préfixes d'outils opérant sur des ressources d'instance.
_ADMIN_ONLY_PREFIXES: tuple[str, ...] = ("ssh_",)

# user_id → (is_admin, expiry_monotonic)
_role_cache: dict[str, tuple[bool, float]] = {}
_ROLE_TTL_S = 60.0


def requires_admin(tool_name: str) -> bool:
    if tool_name.startswith(_ADMIN_ONLY_PREFIXES):
        return True
    try:
        from app.services.mcp_client import mcp_tool_names
        return tool_name in mcp_tool_names()
    except Exception:
        return False


async def _is_admin(user_id: str) -> bool:
    now = time.monotonic()
    cached = _role_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]

    from sqlalchemy import select

    from app.database import async_session
    from app.models.user import User

    try:
        async with async_session() as db:
            role = (await db.execute(
                select(User.role).where(User.id == user_id)
            )).scalar_one_or_none()
        is_admin = role == "admin"
    except Exception as exc:
        logger.warning("tool_acl: lecture du rôle échouée pour %s : %s", user_id, exc)
        is_admin = False  # fail-closed : un doute ≠ un privilège

    _role_cache[user_id] = (is_admin, now + _ROLE_TTL_S)
    return is_admin


async def check_tool_access(user_id: str, tool_name: str) -> str | None:
    """None si autorisé, sinon le message d'erreur à renvoyer comme
    résultat d'outil (l'agent le restitue à l'utilisateur)."""
    if not requires_admin(tool_name):
        return None
    if await _is_admin(user_id):
        return None
    logger.info(
        "tool_acl: %s refusé pour %s (outil d'instance, rôle admin requis)",
        tool_name, user_id,
    )
    return (
        f"⛔ L'outil `{tool_name}` opère sur des ressources de l'instance "
        f"(hôtes SSH / serveurs MCP configurés par l'administrateur) et est "
        f"réservé au rôle admin."
    )


def invalidate_role_cache(user_id: str | None = None) -> None:
    """À appeler quand un rôle change (admin UI)."""
    if user_id is None:
        _role_cache.clear()
    else:
        _role_cache.pop(user_id, None)
