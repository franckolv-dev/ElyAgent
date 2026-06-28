# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/mcp_oauth.py
# @brief      Client MCP v2 — J2 : endpoints OAuth « Se connecter » + callback.
# @license    Elastic License 2.0
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Endpoints OAuth 2.1 du client MCP (J2).

Monté sous ``/api`` (≠ le router MCP admin sous ``/admin``) car le parcours est
**par utilisateur** et le callback doit être joignable par le navigateur sans
auth admin — il est borné par le ``state`` (lié à la session, à usage unique,
TTL court), pas par une session API.

* ``GET /api/mcp/oauth/{server_id}/start`` (auth utilisateur) : découvre l'AS,
  enregistre un client (DCR ou client_id manuel), génère PKCE + state, renvoie
  l'URL de consentement.
* ``GET /api/mcp/oauth/callback`` (sans auth) : valide le state, échange le code,
  range le bundle de tokens dans le Vault du propriétaire, redirige vers l'UI.

Gardé par le flag ``mcp_oauth_enabled`` (OFF par défaut → 404). Refresh /
rotation / révocation = J3. UI « Se connecter » = J4.
"""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.database import async_session
from app.models.mcp_server import MCPServer
from app.models.user import User
from app.services import mcp_credentials, mcp_oauth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])

# state → {"user_id", "server_id", "code_verifier", "ts"}
_pending_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 min
_MAX_PENDING_STATES = 200


def _cleanup_expired_states() -> None:
    now = time.time()
    for k in [k for k, v in _pending_states.items() if now - v.get("ts", 0) > _STATE_TTL]:
        del _pending_states[k]


def _require_flag() -> None:
    if not getattr(get_settings(), "mcp_oauth_enabled", False):
        # 404 plutôt que 403 : la surface n'existe pas tant que le flag est OFF.
        raise HTTPException(status_code=404, detail="OAuth MCP désactivé")


def _visible(srv: MCPServer | None, user_id: str) -> bool:
    """Serveur instance (tous) ou perso (propriétaire seul). Fail-closed."""
    if srv is None:
        return False
    if (srv.scope or "instance") == "instance":
        return True
    return srv.owner_user_id == user_id


def _frontend_redirect(status: str) -> RedirectResponse:
    base = get_settings().frontend_url
    return RedirectResponse(url=f"{base}/settings/mcp?mcp_oauth={status}")


@router.get("/{server_id}/start")
async def oauth_start(server_id: str, current_user: User = Depends(get_current_user)):
    """Démarre le flow OAuth pour un serveur MCP. Renvoie l'URL de consentement."""
    _require_flag()
    _cleanup_expired_states()
    if len(_pending_states) >= _MAX_PENDING_STATES:
        raise HTTPException(status_code=429, detail="Trop de flux OAuth en attente")

    settings = get_settings()
    redirect_uri = settings.mcp_oauth_redirect_uri

    async with async_session() as db:
        srv = await db.get(MCPServer, server_id)
        if not _visible(srv, current_user.id):
            raise HTTPException(status_code=404, detail="Serveur introuvable")
        if (srv.auth_type or "none") != "oauth2" or not srv.url:
            raise HTTPException(status_code=400, detail="Serveur non configuré en OAuth2")

        client = mcp_oauth.default_http_client(
            allow_private=bool(getattr(srv, "allow_private_network", False)),
        )
        try:
            meta = await mcp_oauth.discover_authorization_server(client, srv.url)

            client_id = srv.oauth_client_id
            client_secret_enc = srv.oauth_client_secret_ref
            if not client_id:
                reg_ep = meta.get("registration_endpoint")
                if not reg_ep:
                    raise HTTPException(
                        status_code=400,
                        detail="Pas de client_id et DCR indisponible — renseigner un client_id",
                    )
                reg = await mcp_oauth.register_client(client, reg_ep, redirect_uri)
                client_id = reg["client_id"]
                if reg.get("client_secret"):
                    from app.services.secrets_at_rest import encrypt
                    client_secret_enc = encrypt(reg["client_secret"])
        except mcp_oauth.MCPOAuthError as exc:
            raise HTTPException(status_code=502, detail=f"Découverte OAuth échouée : {exc}")
        finally:
            await client.aclose()

        scope = srv.oauth_scopes or (
            " ".join(meta["scopes_supported"]) if meta.get("scopes_supported") else None
        )
        verifier, challenge = mcp_oauth.generate_pkce_pair()
        state = secrets.token_urlsafe(32)
        auth_url = mcp_oauth.build_authorization_url(
            meta, client_id=client_id, redirect_uri=redirect_uri,
            state=state, code_challenge=challenge, scope=scope,
        )

        # Persistance des métadonnées non secrètes (cache de découverte + client).
        import json as _json
        srv.oauth_metadata_json = _json.dumps(meta, separators=(",", ":"))
        srv.oauth_client_id = client_id
        srv.oauth_client_secret_ref = client_secret_enc
        if scope:
            srv.oauth_scopes = scope
        await db.commit()

    _pending_states[state] = {
        "user_id": current_user.id,
        "server_id": server_id,
        "code_verifier": verifier,
        "ts": time.time(),
    }
    return {"url": auth_url}


@router.get("/callback")
async def oauth_callback(code: str, state: str):
    """Callback du serveur d'autorisation : échange le code, range les tokens."""
    _require_flag()
    _cleanup_expired_states()
    pending = _pending_states.pop(state, None)
    if not pending or time.time() - pending.get("ts", 0) > _STATE_TTL:
        raise HTTPException(status_code=400, detail="State OAuth invalide ou expiré")

    user_id = pending["user_id"]
    server_id = pending["server_id"]
    code_verifier = pending["code_verifier"]
    settings = get_settings()
    redirect_uri = settings.mcp_oauth_redirect_uri

    async with async_session() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is None or not srv.oauth_metadata_json or not srv.oauth_client_id:
            raise HTTPException(status_code=400, detail="Flux OAuth incohérent")

        import json as _json
        meta = _json.loads(srv.oauth_metadata_json)
        client_secret = None
        if srv.oauth_client_secret_ref:
            from app.services.secrets_at_rest import decrypt
            client_secret = decrypt(srv.oauth_client_secret_ref) or None

        client = mcp_oauth.default_http_client(
            allow_private=bool(getattr(srv, "allow_private_network", False)),
        )
        try:
            token = await mcp_oauth.exchange_code(
                client, meta["token_endpoint"],
                code=code, redirect_uri=redirect_uri,
                client_id=srv.oauth_client_id, code_verifier=code_verifier,
                resource=meta["resource"], client_secret=client_secret,
            )
        except mcp_oauth.MCPOAuthError as exc:
            logger.warning("Échange OAuth MCP échoué pour %s : %s", srv.slug, exc)
            return _frontend_redirect("error")
        finally:
            await client.aclose()

        bundle = mcp_oauth.build_bundle(token)
        try:
            ref = await mcp_credentials.store_oauth_bundle(user_id, srv.slug, bundle)
        except PermissionError:
            # Vault verrouillé : on ne contourne pas. L'utilisateur déverrouille
            # puis relance « Se connecter ».
            return _frontend_redirect("locked")

        srv.credential_ref = ref
        srv.auth_type = "oauth2"
        await db.commit()

    return _frontend_redirect("connected")
