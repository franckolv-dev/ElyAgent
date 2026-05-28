# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/google_auth.py
# @brief      Google OAuth2 helpers — handles the authorization flow and token refresh
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
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
import os

# Google may return additional scopes (e.g. drive.readonly alongside drive).
# This tells oauthlib to accept expanded scopes instead of raising an error.
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from app.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    # OpenID + email — needed to identify which Google account just consented.
    # Without these, we can't tell perso@gmail apart from pro@boite.fr in the
    # multi-account flow. Returned in the ID token + queryable via /userinfo.
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.modify",   # read + modify (labels, trash, move)
    "https://www.googleapis.com/auth/gmail.readonly", # kept so Google's scope response matches exactly
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",          # full Drive access (create, edit, delete)
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

    HIGH-3: Only token, refresh_token, token_uri, scopes and expiry are stored
    per-user. client_id and client_secret are NOT stored in user credentials —
    they are always retrieved from settings/DB at runtime to avoid secret
    exposure.

    HOTFIX 2026-05-28 : ``expiry`` was missing from the persisted dict.
    Without it ``Credentials.expired`` always returned False (google-auth
    treats ``expiry=None`` as "never expired"), so ``get_user_credentials``
    never refreshed the access token. Every cron job and every chat session
    older than 1 h hit a 401 then "Google non connecté", even with a valid
    refresh_token. Storing ``expiry`` as ISO-8601 (naive UTC, matching
    google-auth's internal format) fixes this for every new OAuth consent.
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
        # google-auth stores expiry as a *naive UTC* datetime. We serialize
        # to ISO-8601; ``build_credentials`` parses it back exactly the same
        # way. ``None`` is preserved as None for forward compatibility.
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


async def fetch_userinfo(creds_dict: dict) -> dict:
    """Fetch the Google userinfo (email, name, picture) using the access token.

    Used by the multi-account flow to identify which Google account just
    consented — Google returns the email as `email` and a verified flag as
    `email_verified`. Requires the `openid email` scopes (see SCOPES above).

    Returns ``{"email": str, "name": str, "picture": str | None}`` on success.
    Raises ValueError if the token has no userinfo permission or the call fails.
    """
    import httpx

    creds = await build_credentials(creds_dict)
    # Refresh if needed so we don't 401 on a stale token
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request as _GReq
        await asyncio.to_thread(creds.refresh, _GReq())
    token = creds.token
    if not token:
        raise ValueError("No access token available — userinfo fetch impossible")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise ValueError(
            f"Userinfo HTTP {resp.status_code} — scopes 'openid email' missing? "
            f"({resp.text[:200]})"
        )
    data = resp.json()
    email = data.get("email")
    if not email:
        raise ValueError("Userinfo returned no email field")
    return {
        "email": email,
        "name": data.get("name", ""),
        "picture": data.get("picture"),
    }


def _parse_expiry(value):
    """Parse the stored ``expiry`` field back into a naive-UTC datetime.

    google-auth stores ``Credentials.expiry`` as a *naive* datetime in UTC.
    ``exchange_code`` serialises it via ``isoformat()`` which produces a
    naive ISO-8601 string. We parse it back the same way. Anything else
    (timezone-aware string, dict with ``timestamp`` key, None) is handled
    defensively so a malformed legacy row never crashes the refresh path.
    """
    if not value:
        return None
    from datetime import datetime
    try:
        if isinstance(value, datetime):
            # Strip tz if present — google-auth wants naive UTC.
            return value.replace(tzinfo=None) if value.tzinfo is not None else value
        if isinstance(value, str):
            dt = datetime.fromisoformat(value)
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
    except Exception as exc:
        logger.debug("Failed to parse stored credentials expiry %r: %s", value, exc)
    return None


async def build_credentials(creds_dict: dict):
    """Rebuild a Credentials object from stored dict.

    client_id and client_secret are always loaded from settings/DB, never from
    the per-user stored dict (HIGH-3).

    HOTFIX 2026-05-28 : restore ``expiry`` (when present in the stored dict)
    so that ``creds.expired`` reports the truth instead of always returning
    False. Without this, ``get_user_credentials`` skips the refresh and
    every API call eventually 401s after the access token's 1 h lifespan.
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
        expiry=_parse_expiry(creds_dict.get("expiry")),
    )


def _serialize_refreshed(creds) -> str:
    """Re-serialise a refreshed Credentials object back to our storage dict.

    Mirrors the shape produced by ``exchange_code`` so the persistence
    layer can write the new ``credentials_json`` without losing fields.
    Used by ``get_user_credentials`` when it persists a refreshed token
    so the next call doesn't have to refresh again.
    """
    return json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or []),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    })


async def _persist_refreshed_credentials(user_id: str, new_json: str) -> None:
    """Best-effort write of the refreshed creds back to DB + in-memory store.

    Called by ``get_user_credentials`` when a refresh succeeded and the
    caller supplied a ``user_id``. Updates :
      1. The default ``GoogleAccount.credentials_json`` for the user
      2. Legacy ``User.google_credentials`` mirror (for code paths still
         reading the User column)
      3. The in-process ``credential_store`` cache so the next chat turn
         picks up the fresh token without a DB hit.

    Never raises — a persistence failure must not break the calling tool.
    """
    if not user_id or not new_json:
        return
    try:
        from sqlalchemy import select
        from app.database import async_session
        from app.models.google_account import GoogleAccount
        from app.models.user import User

        async with async_session() as db:
            row = (await db.execute(
                select(GoogleAccount).where(
                    GoogleAccount.user_id == user_id,
                    GoogleAccount.is_default == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if row is not None:
                row.credentials_json = new_json
            u = await db.get(User, user_id)
            if u is not None:
                u.google_credentials = new_json
            await db.commit()
        try:
            from app.services.credential_store import get_credential_store
            get_credential_store().set(str(user_id), new_json)
        except Exception:
            pass
        logger.debug("Refreshed Google credentials persisted for user %s…",
                     user_id[:8] if isinstance(user_id, str) else "?")
    except Exception as exc:
        logger.warning(
            "Failed to persist refreshed Google credentials (swallowed): %s",
            exc,
        )


async def get_user_credentials(
    google_credentials_json: str | None,
    *,
    user_id: str | None = None,
):
    """Get refreshed credentials from stored JSON, or None if not connected.

    LOW-5: blocking OAuth network calls are wrapped in asyncio.to_thread.

    HOTFIX 2026-05-28 : two changes that close a long-standing silent
    failure ("Google non connecté" on every cron / stale chat) :

    1. Refresh trigger expanded. The old condition was strict
       ``creds.expired and creds.refresh_token``. With legacy rows that
       were stored before ``expiry`` was tracked, ``creds.expired`` is
       always False (None expiry ≠ expired) so the refresh never ran.
       We now also refresh when ``creds.expiry is None`` and a
       refresh_token exists — that covers every account created before
       the hotfix without forcing the user to re-consent.

    2. Persistence of refreshed token. When ``user_id`` is provided and
       the refresh succeeds, we write the new credentials_json back to
       the default ``GoogleAccount`` row (and mirror to ``User``). Without
       this, every tool call would refresh from scratch (~200 ms overhead).
       Best-effort — a write failure never blocks the returned creds.
    """
    if not google_credentials_json:
        return None
    try:
        creds_dict = json.loads(google_credentials_json)
        creds = await build_credentials(creds_dict)
        # Force refresh if (a) the token is known to be expired, OR
        # (b) we have no expiry info but we DO have a refresh_token —
        # the legacy-row safety net.
        legacy_no_expiry = (creds.expiry is None) and bool(creds.refresh_token)
        if (creds.expired or legacy_no_expiry) and creds.refresh_token:
            from google.auth.transport.requests import Request
            try:
                await asyncio.to_thread(creds.refresh, Request())
            except Exception as refresh_exc:
                logger.warning(
                    "Google token refresh failed: %s — returning stale creds, "
                    "API call will likely 401",
                    refresh_exc,
                )
                return creds
            # Refresh succeeded — persist so subsequent calls don't repeat
            # the round-trip. Persistence requires a user_id; without one
            # the caller will just refresh again next time (still correct,
            # just ~200 ms slower).
            if user_id:
                try:
                    await _persist_refreshed_credentials(
                        user_id, _serialize_refreshed(creds),
                    )
                except Exception:
                    pass
        return creds
    except Exception as exc:
        logger.warning("Failed to load Google credentials: %s", exc)
        return None
