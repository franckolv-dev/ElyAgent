# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_credentials.py
# @brief      Credentials des serveurs MCP — stockés dans le Vault, jamais ici.
# @license    MIT
#            https://opensource.org/licenses/MIT
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
refresh/rotation en J3.

V2 — J3 (refresh/rotation/révocation) : ``resolve_user_headers`` devient
refresh-aware — si l'access token est expiré (avec marge), on le rafraîchit une
fois (grant_type=refresh_token), on persiste le nouveau bundle (rotation du
refresh token) puis on renvoie le Bearer frais. Si aucun token utilisable
(bundle absent/purgé, refresh expiré/révoqué) → ``MCPAuthRequired`` (l'appelant
déclenche une ré-autorisation). ``revoke_oauth`` révoque côté AS (best-effort)
puis purge le bundle.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# Marge avant expiration : on rafraîchit un peu en avance pour éviter qu'un token
# expire pendant l'appel.
_REFRESH_LEEWAY_SECONDS = 60


class MCPAuthRequired(Exception):
    """Le serveur OAuth2 n'a pas de token utilisable — (ré)autorisation requise."""


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
        return await _oauth2_headers(user_id, srv)

    from app.services.vault_service import get_vault_service

    secret = await get_vault_service().get_secret(user_id, ref)
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth_type == "api_key":
        header = getattr(srv, "auth_header_name", None) or "X-API-Key"
        return {header: secret}
    logger.warning("MCP auth_type inconnu : %s", auth_type)
    return None


# ── OAuth2 : résolution refresh-aware (J3) ───────────────────────────────────

async def _oauth2_headers(user_id: str, srv) -> dict[str, str]:
    """Bearer OAuth2 frais : refresh proactif si l'access token est expiré.

    Lève ``PermissionError`` si le Vault est verrouillé (fail-closed),
    ``MCPAuthRequired`` si aucun token utilisable (bundle purgé, refresh
    expiré/révoqué)."""
    try:
        bundle = await load_oauth_bundle(user_id, srv)
    except KeyError:
        # Secret purgé (déconnexion) ⇒ ré-autorisation requise.
        raise MCPAuthRequired("Bundle OAuth absent — reconnexion requise")
    if not bundle or not bundle.get("access_token"):
        raise MCPAuthRequired("Aucun token OAuth — connexion requise")

    expires_at = bundle.get("expires_at")
    if expires_at is None or time.time() < expires_at - _REFRESH_LEEWAY_SECONDS:
        return {"Authorization": f"Bearer {bundle['access_token']}"}

    refreshed = await _refresh_oauth_bundle(user_id, srv, bundle)
    return {"Authorization": f"Bearer {refreshed['access_token']}"}


async def _refresh_oauth_bundle(user_id: str, srv, bundle: dict) -> dict:
    """Rafraîchit le bundle (refresh-once), persiste la rotation, le renvoie."""
    rt = bundle.get("refresh_token")
    meta_raw = getattr(srv, "oauth_metadata_json", None)
    client_id = getattr(srv, "oauth_client_id", None)
    if not rt or not meta_raw or not client_id:
        raise MCPAuthRequired("Refresh impossible — reconnexion requise")
    try:
        meta = json.loads(meta_raw)
    except (json.JSONDecodeError, TypeError):
        raise MCPAuthRequired("Métadonnées OAuth illisibles — reconnexion requise")
    token_endpoint = meta.get("token_endpoint")
    resource = meta.get("resource")
    if not token_endpoint or not resource:
        raise MCPAuthRequired("Métadonnées OAuth incomplètes — reconnexion requise")

    client_secret = None
    if getattr(srv, "oauth_client_secret_ref", None):
        from app.services.secrets_at_rest import decrypt
        client_secret = decrypt(srv.oauth_client_secret_ref) or None

    from app.services import mcp_oauth

    client = mcp_oauth.default_http_client(
        allow_private=bool(getattr(srv, "allow_private_network", False)))
    try:
        token = await mcp_oauth.refresh_access_token(
            client, token_endpoint, refresh_token=rt, client_id=client_id,
            resource=resource, client_secret=client_secret,
        )
    except mcp_oauth.MCPOAuthError as exc:
        # Refresh expiré/révoqué : on ne garde pas un bundle inutilisable.
        raise MCPAuthRequired("Refresh refusé — reconnexion requise") from exc
    finally:
        await client.aclose()

    new_bundle = mcp_oauth.build_bundle(token, prev_refresh_token=rt)
    # Overwrite sous le même label (credential_ref inchangé).
    await store_oauth_bundle(user_id, getattr(srv, "slug", ""), new_bundle)
    return new_bundle


async def revoke_oauth(user_id: str, srv) -> None:
    """Révoque les tokens OAuth d'un utilisateur côté AS (best-effort) puis purge
    le bundle local. Ne lève pas : une révocation distante en échec ne doit pas
    empêcher la purge locale."""
    try:
        bundle = await load_oauth_bundle(user_id, srv)
    except (KeyError, PermissionError):
        bundle = None

    meta_raw = getattr(srv, "oauth_metadata_json", None)
    if bundle and meta_raw:
        try:
            meta = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            meta = {}
        rev = meta.get("revocation_endpoint")
        rt = bundle.get("refresh_token") or bundle.get("access_token")
        if rev and rt:
            from app.services import mcp_oauth

            client = mcp_oauth.default_http_client(
                allow_private=bool(getattr(srv, "allow_private_network", False)))
            try:
                await mcp_oauth.revoke_token(
                    client, rev, rt, client_id=getattr(srv, "oauth_client_id", None))
            finally:
                await client.aclose()

    await clear_oauth_bundle(user_id, srv)
