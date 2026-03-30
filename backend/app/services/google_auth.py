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
"""Google OAuth2 helpers — handles the authorization flow and token refresh.

Credential priority (for client_id / client_secret):
  1. system_config table (set via admin UI)
  2. GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET env vars / config.py
  3. Raise ValueError → Google not configured
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",   # read + modify (labels, trash, move)
    "https://www.googleapis.com/auth/gmail.readonly", # kept so Google's scope response matches exactly
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts",
]


async def _get_oauth_client() -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri) — DB overrides env."""
    from app.services.system_config import get_config

    s = get_settings()
    client_id    = await get_config("google_client_id",     fallback=s.google_client_id)
    client_secret = await get_config("google_client_secret", fallback=s.google_client_secret)
    redirect_uri  = await get_config("google_redirect_uri",  fallback=s.google_redirect_uri)

    if not client_id or not client_secret:
        raise ValueError(
            "Google OAuth2 non configuré. "
            "Renseignez les credentials dans Admin → Configuration OAuth."
        )
    return client_id, client_secret, redirect_uri


async def get_flow():
    """Build an OAuth2 Flow (async — reads credentials from DB)."""
    from google_auth_oauthlib.flow import Flow

    client_id, client_secret, redirect_uri = await _get_oauth_client()
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


async def build_auth_url(state: str) -> tuple[str, str | None]:
    """Generate the Google authorization URL.

    Returns (auth_url, code_verifier).  code_verifier is non-None when the
    library added PKCE automatically (google-auth-oauthlib >= 1.x); it must
    be stored and passed back to exchange_code().
    """
    flow = await get_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    # google-auth-oauthlib ≥ 1.0 automatically adds PKCE; grab the verifier.
    code_verifier: str | None = getattr(flow, "code_verifier", None)
    return auth_url, code_verifier


async def exchange_code(code: str, code_verifier: str | None = None) -> dict:
    """Exchange authorization code for tokens.

    HIGH-3: Only token, refresh_token, token_uri, and scopes are stored per-user.
    client_id and client_secret are NOT stored in user credentials — they are
    always retrieved from settings/DB at runtime to avoid secret exposure.
    """
    flow = await get_flow()
    fetch_kwargs: dict = {"code": code}
    if code_verifier:
        fetch_kwargs["code_verifier"] = code_verifier
    await asyncio.to_thread(flow.fetch_token, **fetch_kwargs)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or []),
    }


async def build_credentials(creds_dict: dict):
    """Rebuild a Credentials object from stored dict.

    client_id and client_secret are always loaded from settings/DB, never from
    the per-user stored dict (HIGH-3).
    """
    from google.oauth2.credentials import Credentials
    client_id, client_secret, _redirect = await _get_oauth_client()
    return Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=creds_dict.get("scopes"),
    )


async def get_user_credentials(google_credentials_json: str | None):
    """Get refreshed credentials from stored JSON, or None if not connected.

    LOW-5: blocking OAuth network calls are wrapped in asyncio.to_thread.
    """
    if not google_credentials_json:
        return None
    try:
        creds_dict = json.loads(google_credentials_json)
        creds = await build_credentials(creds_dict)
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            await asyncio.to_thread(creds.refresh, Request())
        return creds
    except Exception as exc:
        logger.warning("Failed to load Google credentials: %s", exc)
        return None
