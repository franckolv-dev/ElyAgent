# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_oauth.py
# @brief      Client MCP v2 — J2 : flow OAuth 2.1 / PKCE (découverte + échange).
# @license    Elastic License 2.0
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Mécanique OAuth 2.1 d'un serveur MCP distant (J2).

Périmètre J2 (cf. ``docs_internes/cadrage_mcp_v2.md``) :

* découverte du serveur d'autorisation : RFC 9728 (Protected Resource Metadata)
  → RFC 8414 (Authorization Server Metadata), avec replis OIDC / origine ;
* Dynamic Client Registration (RFC 7591) avec **repli sur un client_id manuel** ;
* PKCE S256 obligatoire ;
* construction de l'URL d'autorisation (``resource`` RFC 8707, scopes minimaux) ;
* échange du code contre les tokens.

Le **refresh / la rotation / la révocation** relèvent de J3. Le stockage des
tokens (bundle Vault) et la résolution des en-têtes vivent dans
``mcp_credentials`` (J1). Ici : aucune persistance, aucune dépendance au modèle —
des fonctions pures + un client HTTP **injectable** (défaut = factory gardée
SSRF/rebinding de ``mcp_egress``), pour des tests hermétiques.

Tous les hops HTTP (découverte, DCR, token) passent par la même garde egress que
les connexions MCP : HTTPS imposé, IP validée et épinglée, redirections
re-validées. Aucun token ni ``code`` n'est journalisé.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode, urlsplit

logger = logging.getLogger(__name__)


class MCPOAuthError(Exception):
    """Échec d'une étape OAuth (découverte, DCR, échange). Sans secret."""


# ── PKCE ───────────────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Renvoie ``(code_verifier, code_challenge)`` en S256 (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)  # 86 chars, dans la borne 43..128
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── HTTP gardé (injectable) ──────────────────────────────────────────────────

def default_http_client(*, allow_private: bool = False):
    """Client httpx gardé SSRF/rebinding (HTTPS imposé) pour les hops OAuth."""
    from app.services.mcp_egress import build_guarded_http_factory

    return build_guarded_http_factory(
        allow_private=allow_private, require_https=True,
    )()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise MCPOAuthError("URL serveur MCP invalide")
    return f"{parts.scheme}://{parts.netloc}"


async def _get_json(client, url: str) -> dict | None:
    """GET tolérant : renvoie le JSON ou None (404 / non-JSON / erreur réseau)."""
    try:
        resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001 — un endpoint de découverte absent ≠ fatal
        logger.info("Découverte OAuth : GET %s a échoué (%s)", url, type(exc).__name__)
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


# ── Découverte (RFC 9728 → RFC 8414 / OIDC) ─────────────────────────────────

async def discover_authorization_server(client, server_url: str) -> dict:
    """Découvre les métadonnées du serveur d'autorisation pour un serveur MCP.

    Chaîne : RFC 9728 (``/.well-known/oauth-protected-resource``) pour obtenir
    l'AS, puis RFC 8414 (``/.well-known/oauth-authorization-server``) avec repli
    OIDC (``/.well-known/openid-configuration``). Si la PRM est absente, on
    suppose que le serveur MCP est son propre AS (origine). ``MCPOAuthError`` si
    aucun jeu d'endpoints exploitable.

    Renvoie un dict contenant au moins ``authorization_endpoint`` et
    ``token_endpoint`` ; ``registration_endpoint``/``scopes_supported`` si
    annoncés ; plus ``issuer`` et ``resource`` (l'origine du serveur MCP)."""
    resource = _origin(server_url)

    # 1. RFC 9728 — Protected Resource Metadata → liste d'AS.
    prm = await _get_json(client, f"{resource}/.well-known/oauth-protected-resource")
    as_candidates: list[str] = []
    if prm:
        servers = prm.get("authorization_servers")
        if isinstance(servers, list):
            as_candidates = [s for s in servers if isinstance(s, str) and s]
    if not as_candidates:
        # Repli : le serveur MCP est son propre AS.
        as_candidates = [resource]

    # 2. RFC 8414 / OIDC sur le premier AS exploitable.
    for as_url in as_candidates:
        as_origin = _origin(as_url)
        for well_known in (
            f"{as_origin}/.well-known/oauth-authorization-server",
            f"{as_origin}/.well-known/openid-configuration",
        ):
            meta = await _get_json(client, well_known)
            if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                return {
                    "issuer": meta.get("issuer", as_origin),
                    "resource": resource,
                    "authorization_endpoint": meta["authorization_endpoint"],
                    "token_endpoint": meta["token_endpoint"],
                    "registration_endpoint": meta.get("registration_endpoint"),
                    "revocation_endpoint": meta.get("revocation_endpoint"),
                    "scopes_supported": meta.get("scopes_supported"),
                }
    raise MCPOAuthError("Aucun serveur d'autorisation OAuth exploitable découvert")


# ── Dynamic Client Registration (RFC 7591) ──────────────────────────────────

async def register_client(client, registration_endpoint: str, redirect_uri: str,
                          *, client_name: str = "Ely") -> dict:
    """Enregistre dynamiquement un client public (PKCE, sans secret).

    Renvoie ``{"client_id": ..., "client_secret": ... | None}``. ``MCPOAuthError``
    si l'enregistrement échoue (l'appelant retombe alors sur un client_id manuel)."""
    body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # client public → PKCE seul
    }
    try:
        resp = await client.post(registration_endpoint, json=body)
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError(f"DCR injoignable ({type(exc).__name__})") from exc
    if resp.status_code not in (200, 201):
        raise MCPOAuthError(f"DCR refusée (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError("Réponse DCR illisible") from exc
    cid = data.get("client_id")
    if not cid:
        raise MCPOAuthError("DCR sans client_id")
    return {"client_id": cid, "client_secret": data.get("client_secret")}


# ── URL d'autorisation ──────────────────────────────────────────────────────

def build_authorization_url(meta: dict, *, client_id: str, redirect_uri: str,
                            state: str, code_challenge: str,
                            scope: str | None) -> str:
    """Construit l'URL d'autorisation (Authorization Code + PKCE S256).

    Inclut ``resource`` (RFC 8707) = l'origine du serveur MCP, pour empêcher le
    passthrough de token vers une autre ressource."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": meta["resource"],
    }
    if scope:
        params["scope"] = scope
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return f"{meta['authorization_endpoint']}{sep}{urlencode(params)}"


# ── Échange code → tokens ────────────────────────────────────────────────────

async def exchange_code(client, token_endpoint: str, *, code: str, redirect_uri: str,
                        client_id: str, code_verifier: str, resource: str,
                        client_secret: str | None = None) -> dict:
    """Échange le code d'autorisation contre des tokens (form-urlencoded)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "resource": resource,
    }
    if client_secret:
        data["client_secret"] = client_secret
    try:
        resp = await client.post(
            token_endpoint, data=data,
            headers={"Accept": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError(f"Token endpoint injoignable ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise MCPOAuthError(f"Échange du code refusé (HTTP {resp.status_code})")
    try:
        token = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError("Réponse token illisible") from exc
    if not token.get("access_token"):
        raise MCPOAuthError("Réponse token sans access_token")
    return token


# ── Refresh (J3) ─────────────────────────────────────────────────────────────

async def refresh_access_token(client, token_endpoint: str, *, refresh_token: str,
                               client_id: str, resource: str,
                               client_secret: str | None = None,
                               scope: str | None = None) -> dict:
    """Rafraîchit l'access token (grant_type=refresh_token, form-urlencoded).

    Renvoie la réponse token brute. ``MCPOAuthError`` si l'AS refuse (refresh
    expiré/révoqué → l'appelant déclenche une ré-autorisation)."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "resource": resource,
    }
    if client_secret:
        data["client_secret"] = client_secret
    if scope:
        data["scope"] = scope
    try:
        resp = await client.post(
            token_endpoint, data=data, headers={"Accept": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError(f"Token endpoint injoignable ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise MCPOAuthError(f"Refresh refusé (HTTP {resp.status_code})")
    try:
        token = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise MCPOAuthError("Réponse refresh illisible") from exc
    if not token.get("access_token"):
        raise MCPOAuthError("Réponse refresh sans access_token")
    return token


# ── Révocation (RFC 7009, J3) ────────────────────────────────────────────────

async def revoke_token(client, revocation_endpoint: str, token: str, *,
                       token_type_hint: str = "refresh_token",
                       client_id: str | None = None,
                       client_secret: str | None = None) -> bool:
    """Révoque un token auprès de l'AS (best-effort). Renvoie True si 200.

    Ne lève pas : une révocation distante qui échoue ne doit pas bloquer la
    purge locale du bundle (cf. mcp_credentials.revoke_oauth)."""
    data = {"token": token, "token_type_hint": token_type_hint}
    if client_id:
        data["client_id"] = client_id
    if client_secret:
        data["client_secret"] = client_secret
    try:
        resp = await client.post(revocation_endpoint, data=data)
    except Exception as exc:  # noqa: BLE001
        logger.info("Révocation OAuth injoignable (%s)", type(exc).__name__)
        return False
    return resp.status_code == 200


def build_bundle(token_response: dict, *, now: float | None = None,
                 prev_refresh_token: str | None = None) -> dict:
    """Normalise une réponse token en bundle Vault (cf. mcp_credentials).

    ``expires_at`` est calculé depuis ``expires_in`` (epoch). Rotation des
    refresh tokens : on garde celui de la réponse s'il est présent, sinon on
    conserve ``prev_refresh_token`` (certains AS ne renvoient le refresh qu'une
    fois)."""
    ts = time.time() if now is None else now
    expires_in = token_response.get("expires_in")
    bundle = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token") or prev_refresh_token,
        "token_type": token_response.get("token_type", "Bearer"),
        "scope": token_response.get("scope"),
        "obtained_at": int(ts),
    }
    if isinstance(expires_in, (int, float)):
        bundle["expires_at"] = int(ts) + int(expires_in)
    return bundle
