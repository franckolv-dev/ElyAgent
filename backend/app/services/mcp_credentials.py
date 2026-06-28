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

V2 — J1 (socle OAuth) : le **bundle OAuth** (access/refresh tokens, expiration,
scopes) est rangé comme un secret JSON dans le Vault du propriétaire, sous un
label dédié ``mcp::<slug>::oauth``. Pas de table de tokens : le Vault est la
source de vérité. Le flow (découverte AS, PKCE, échange code) arrive en J2 ; le
refresh/rotation en J3. Ici, on ne pose que la plomberie de stockage/lecture +
la branche ``oauth2`` de ``resolve_user_headers`` (Bearer depuis le bundle, sans
refresh — l'expiration sera gérée en J3).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def credential_label(slug: str) -> str:
    return f"mcp::{slug}::credential"


def oauth_label(slug: str) -> str:
    """Label Vault du bundle OAuth d'un serveur (distinct de ``credential``)."""
    return f"mcp::{slug}::oauth"


async def store_user_credential(user_id: str, slug: str, secret: str) -> str:
    """Chiffre le secret dans le Vault du propriétaire. Renvoie le ``credential_ref``."""
    from app.services.vault_service import get_vault_service

    label = credential_label(slug)
    await get_vault_service().store_secret(
        user_id, label, secret, hint=f"Credential MCP {slug}",
    )
    return label


async def store_oauth_bundle(user_id: str, slug: str, bundle: dict) -> str:
    """Chiffre le bundle OAuth (JSON) dans le Vault du propriétaire.

    Le bundle contient typiquement ``access_token``, ``refresh_token``,
    ``expires_at`` (epoch), ``token_type``, ``scope``, ``obtained_at``. Renvoie
    le label Vault à stocker dans ``credential_ref`` — jamais le secret."""
    from app.services.vault_service import get_vault_service

    label = oauth_label(slug)
    await get_vault_service().store_secret(
        user_id, label, json.dumps(bundle, separators=(",", ":")),
        hint=f"OAuth MCP {slug}",
    )
    return label


async def load_oauth_bundle(user_id: str, srv) -> dict | None:
    """Lit et désérialise le bundle OAuth depuis le Vault du propriétaire.

    Renvoie ``None`` si le serveur n'est pas en oauth2 ou n'a pas de référence
    (pas encore connecté). Lève ``PermissionError`` si le coffre est verrouillé
    (fail-closed : on ne contourne pas le verrou), ``KeyError`` si le secret a
    disparu. Un bundle illisible (JSON corrompu) est traité comme absent."""
    auth_type = getattr(srv, "auth_type", "none") or "none"
    ref = getattr(srv, "credential_ref", None)
    if auth_type != "oauth2" or not ref:
        return None

    from app.services.vault_service import get_vault_service

    raw = await get_vault_service().get_secret(user_id, ref)
    try:
        bundle = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Bundle OAuth MCP illisible pour %s", getattr(srv, "slug", "?"))
        return None
    return bundle if isinstance(bundle, dict) else None


async def clear_oauth_bundle(user_id: str, srv) -> None:
    """Supprime le bundle OAuth du Vault (déconnexion / révocation). Best-effort."""
    ref = getattr(srv, "credential_ref", None)
    if not ref:
        return
    from app.services.vault_service import get_vault_service

    try:
        await get_vault_service().delete_secret(user_id, ref)
    except Exception:  # noqa: BLE001 — best-effort, ne jamais bloquer la révocation
        logger.warning("Échec purge bundle OAuth MCP pour %s", getattr(srv, "slug", "?"))


async def resolve_user_headers(user_id: str, srv) -> dict[str, str] | None:
    """En-têtes d'auth pour un appel utilisateur. None si pas d'auth.

    Lève ``PermissionError`` si le coffre est verrouillé (fail-closed : on ne
    contourne pas le verrou), ``KeyError`` si le secret a disparu."""
    auth_type = getattr(srv, "auth_type", "none") or "none"
    ref = getattr(srv, "credential_ref", None)
    if auth_type == "none" or not ref:
        return None

    if auth_type == "oauth2":
        # J1 : Bearer depuis le bundle Vault, sans refresh (l'expiration et la
        # rotation arrivent en J3). Bundle absent/illisible ⇒ pas d'en-tête →
        # le serveur répondra 401, traité comme MCP_AUTH_REQUIRED en aval.
        bundle = await load_oauth_bundle(user_id, srv)
        token = (bundle or {}).get("access_token")
        if not token:
            return None
        return {"Authorization": f"Bearer {token}"}

    from app.services.vault_service import get_vault_service

    secret = await get_vault_service().get_secret(user_id, ref)
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth_type == "api_key":
        header = getattr(srv, "auth_header_name", None) or "X-API-Key"
        return {header: secret}
    logger.warning("MCP auth_type inconnu : %s", auth_type)
    return None
