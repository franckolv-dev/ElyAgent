# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_credentials.py
# @brief      Credentials des serveurs MCP — stockés dans le Vault, jamais ici.
# @license    Elastic License 2.0
# =============================================================================
"""Gestion des credentials d'un serveur MCP distant (J4).

Invariants (cadrage §10.4, §13) :

* le secret n'est **jamais** stocké dans les tables MCP ni renvoyé par l'API —
  seule une référence opaque (label Vault) est conservée dans ``credential_ref`` ;
* le secret n'est **jamais** passé au modèle ni journalisé ;
* les tokens d'un serveur ``scope=user`` vivent dans le **Vault du propriétaire**.

V1 : ``bearer`` et ``api_key`` pour les serveurs personnels (le chemin
model-facing a le contexte utilisateur). Les serveurs d'instance distants
authentifiés relèvent du V2 (le Vault est par-utilisateur — il faut un secret
d'instance dédié, cf. note de cadrage).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def credential_label(slug: str) -> str:
    return f"mcp::{slug}::credential"


async def store_user_credential(user_id: str, slug: str, secret: str) -> str:
    """Chiffre le secret dans le Vault du propriétaire. Renvoie le ``credential_ref``."""
    from app.services.vault_service import get_vault_service

    label = credential_label(slug)
    await get_vault_service().store_secret(
        user_id, label, secret, hint=f"Credential MCP {slug}",
    )
    return label


async def resolve_user_headers(user_id: str, srv) -> dict[str, str] | None:
    """En-têtes d'auth pour un appel utilisateur. None si pas d'auth.

    Lève ``PermissionError`` si le coffre est verrouillé (fail-closed : on ne
    contourne pas le verrou), ``KeyError`` si le secret a disparu."""
    auth_type = getattr(srv, "auth_type", "none") or "none"
    ref = getattr(srv, "credential_ref", None)
    if auth_type == "none" or not ref:
        return None

    from app.services.vault_service import get_vault_service

    secret = await get_vault_service().get_secret(user_id, ref)
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth_type == "api_key":
        header = getattr(srv, "auth_header_name", None) or "X-API-Key"
        return {header: secret}
    logger.warning("MCP auth_type inconnu : %s", auth_type)
    return None
