# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/google.py
# @brief      Google OAuth2 endpoints — multi-account support
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Google OAuth2 endpoints — multi-account support.

Each ELY user can link several Google accounts (perso, perso2, pro). They
are stored in the ``google_accounts`` table with an alias chosen by the
user. Exactly one account per user is flagged ``is_default = True`` and
mirrored into the legacy ``User.google_credentials`` column for backward
compatibility with tools that still read from there.

Flow:
  1. UI calls GET /google/auth-url?alias=pro     → returns Google consent URL
  2. User consents on Google. Google redirects to /google/callback?code=…&state=…
  3. We exchange the code for tokens, fetch the userinfo (email),
     INSERT into google_accounts, and update the legacy User.google_credentials
     so untouched tools keep working.
  4. UI calls GET /google/accounts to render the list.
"""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db, async_session
from app.models.google_account import GoogleAccount
from app.models.user import User
from app.services.google_auth import build_auth_url, exchange_code, fetch_userinfo

router = APIRouter(prefix="/google", tags=["google"])

# state → {"user_id": str, "code_verifier": str | None, "alias": str, "ts": float}
_pending_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 minutes
_MAX_PENDING_STATES = 200


def _cleanup_expired_states() -> None:
    """Remove OAuth states older than _STATE_TTL seconds."""
    now = time.time()
    expired = [k for k, v in _pending_states.items() if now - v.get("ts", 0) > _STATE_TTL]
    for k in expired:
        del _pending_states[k]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _set_default_account(db: AsyncSession, user_id: str, account_id: str) -> None:
    """Mark `account_id` as the default and unflag every other account for the user.

    Also mirrors the credentials JSON into the legacy ``User.google_credentials``
    column so untouched tools (those still reading from there) keep working.
    """
    rows = await db.execute(
        select(GoogleAccount).where(GoogleAccount.user_id == user_id)
    )
    target_creds: str | None = None
    for acc in rows.scalars():
        is_target = acc.id == account_id
        acc.is_default = is_target
        if is_target:
            target_creds = acc.credentials_json
    # Mirror into User for backward compat
    if target_creds is not None:
        u = await db.get(User, user_id)
        if u is not None:
            u.google_credentials = target_creds
            # Refresh the in-process credential store. str() so the cache
            # key matches what the WebSocket session uses (JWT sub).
            from app.services.credential_store import get_credential_store
            get_credential_store().set(str(user_id), target_creds)


def _account_to_dict(acc: GoogleAccount) -> dict:
    return {
        "id": acc.id,
        "alias": acc.alias,
        "email": acc.email,
        "is_default": acc.is_default,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# OAuth flow — multi-account
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/auth-url")
async def get_auth_url(
    alias: str = "perso",
    current_user: User = Depends(get_current_user),
):
    """Generate Google OAuth URL for the current user.

    `alias` is the human label this account will receive in the user's
    list. Default `"perso"` for backward compat — when only one account
    is linked, the UI shows it as such.
    """
    try:
        _cleanup_expired_states()
        if len(_pending_states) >= _MAX_PENDING_STATES:
            raise HTTPException(status_code=429, detail="Trop de demandes OAuth en attente")
        # Validate alias (50 chars, no funky stuff so it stays UI-safe)
        alias = (alias or "perso").strip()[:50]
        if not alias:
            alias = "perso"
        state = secrets.token_urlsafe(32)
        url, code_verifier = await build_auth_url(state)
        _pending_states[state] = {
            "user_id": current_user.id,
            "code_verifier": code_verifier,
            "alias": alias,
            "ts": time.time(),
        }
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/callback")
async def oauth_callback(code: str, state: str):
    """Google redirects here after user consent.

    Stores tokens as a new GoogleAccount row, sets it as the default if
    it is the first account, otherwise leaves the existing default
    untouched. Mirrors creds into the legacy User.google_credentials so
    untouched tools keep working.
    """
    _cleanup_expired_states()
    pending = _pending_states.pop(state, None)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if time.time() - pending.get("ts", 0) > _STATE_TTL:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    user_id = pending["user_id"]
    code_verifier = pending.get("code_verifier")
    alias = pending.get("alias") or "perso"

    try:
        creds_dict = await exchange_code(code, code_verifier=code_verifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    # Identify which Google account just consented
    try:
        userinfo = await fetch_userinfo(creds_dict)
        email = userinfo["email"]
    except Exception as e:
        # Backward compat : if the OAuth app hasn't been re-consented since
        # we added the openid/email scopes, the userinfo call fails. We
        # store the account anyway with a placeholder email so the user
        # isn't blocked — they can rename / re-link later.
        email = f"unknown-{secrets.token_hex(4)}@google.local"
        # Log but don't 500
        import logging
        logging.getLogger(__name__).warning(
            "Userinfo fetch failed (%s) — storing account with placeholder email", e
        )

    creds_json = json.dumps(creds_dict)
    redirect_target = "?google=connected"

    async with async_session() as db:
        # If this email is already linked, update the credentials in place
        # rather than create a duplicate (re-consent flow).
        existing = await db.execute(
            select(GoogleAccount).where(
                GoogleAccount.user_id == user_id,
                GoogleAccount.email == email,
            )
        )
        existing_acc = existing.scalar_one_or_none()
        if existing_acc is not None:
            existing_acc.credentials_json = creds_json
            existing_acc.alias = alias  # allow user to rename via re-link
            await db.commit()
            await _set_default_account(db, user_id, existing_acc.id) if existing_acc.is_default else None
            # FIX 2026-05-07 : on re-consent, ALSO refresh the legacy
            # User.google_credentials column AND the in-process credential
            # store. Without this, the WebSocket session keeps reading the
            # stale token (cached for up to 5 min) and tools fail with
            # « Google account disconnected » even though the user just
            # reconnected. Original code only updated User.* on FIRST
            # account creation (line ~237 below).
            if existing_acc.is_default:
                u = await db.get(User, user_id)
                if u is not None:
                    u.google_credentials = creds_json
                from app.services.credential_store import get_credential_store
                # Use str() so the cache key matches what the WebSocket
                # session uses (JWT sub is always a string, while
                # current_user.id is a UUID object — same value, different
                # dict-key identity).
                get_credential_store().set(str(user_id), creds_json)
            await db.commit()
            redirect_target = "?google=updated"
        else:
            # Resolve alias collision (if user already used "perso" for a
            # different account) by suffixing with -2, -3, …
            alias_base = alias
            n = 2
            while True:
                clash = await db.execute(
                    select(GoogleAccount).where(
                        GoogleAccount.user_id == user_id,
                        GoogleAccount.alias == alias,
                    )
                )
                if clash.scalar_one_or_none() is None:
                    break
                alias = f"{alias_base}-{n}"
                n += 1

            # First account for this user becomes the default automatically
            count_q = await db.execute(
                select(GoogleAccount).where(GoogleAccount.user_id == user_id)
            )
            is_first = count_q.scalar_one_or_none() is None

            new_acc = GoogleAccount(
                user_id=user_id,
                alias=alias,
                email=email,
                credentials_json=creds_json,
                is_default=is_first,
            )
            db.add(new_acc)
            await db.flush()
            if is_first:
                # Mirror into User.google_credentials for legacy tools
                u = await db.get(User, user_id)
                if u is not None:
                    u.google_credentials = creds_json
                    from app.services.credential_store import get_credential_store
                    # str() to match the WebSocket session's key (JWT sub).
                    get_credential_store().set(str(user_id), creds_json)
            await db.commit()
            redirect_target = "?google=connected" if is_first else "?google=added"

    s = get_settings()
    return RedirectResponse(url=f"{s.frontend_url}/settings{redirect_target}")


# ──────────────────────────────────────────────────────────────────────────────
# Multi-account REST CRUD
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all Google accounts linked to the current user."""
    rows = await db.execute(
        select(GoogleAccount)
        .where(GoogleAccount.user_id == current_user.id)
        .order_by(GoogleAccount.created_at.asc())
    )
    return {"accounts": [_account_to_dict(a) for a in rows.scalars()]}


class _SetDefaultBody(BaseModel):
    account_id: str = Field(..., min_length=1)


@router.post("/accounts/default")
async def set_default(
    req: _SetDefaultBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a given account as the default — used by tools that don't pick an alias."""
    target = await db.get(GoogleAccount, req.account_id)
    if not target or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    await _set_default_account(db, current_user.id, req.account_id)
    await db.commit()
    return {"message": "Default updated", "account_id": req.account_id}


class _RenameBody(BaseModel):
    alias: str = Field(..., min_length=1, max_length=50)


@router.patch("/accounts/{account_id}")
async def rename_account(
    account_id: str,
    req: _RenameBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename the alias of a Google account."""
    acc = await db.get(GoogleAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    new_alias = req.alias.strip()[:50]
    if not new_alias:
        raise HTTPException(status_code=400, detail="Alias must not be empty")
    # Prevent alias collision within the same user
    clash = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.user_id == current_user.id,
            GoogleAccount.alias == new_alias,
            GoogleAccount.id != account_id,
        )
    )
    if clash.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Alias '{new_alias}' already in use")
    acc.alias = new_alias
    await db.commit()
    return _account_to_dict(acc)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a Google account. If it was the default and another account exists,
    promote the next-oldest account to default. If it was the last one, also
    clear the legacy User.google_credentials column."""
    acc = await db.get(GoogleAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    was_default = acc.is_default
    await db.delete(acc)
    await db.flush()

    if was_default:
        rows = await db.execute(
            select(GoogleAccount)
            .where(GoogleAccount.user_id == current_user.id)
            .order_by(GoogleAccount.created_at.asc())
        )
        next_default = rows.scalars().first()
        if next_default:
            await _set_default_account(db, current_user.id, next_default.id)
        else:
            # No accounts left — clear the legacy column too
            current_user.google_credentials = None
            from app.services.credential_store import get_credential_store
            get_credential_store().clear(str(current_user.id))
    await db.commit()
    return {"message": "Account removed"}


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compat status / disconnect — used by the existing UI
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check Google connection status — true if at least one account is linked.

    Mostly kept for backward compat with the existing settings page; new UI
    should rely on /google/accounts which returns the full list.
    """
    rows = await db.execute(
        select(GoogleAccount).where(GoogleAccount.user_id == current_user.id)
    )
    accounts = list(rows.scalars())
    if accounts:
        return {
            "connected": True,
            "accounts_count": len(accounts),
            "default_email": next((a.email for a in accounts if a.is_default), None),
        }
    # Legacy fallback : honour User.google_credentials if no GoogleAccount row exists
    return {"connected": current_user.google_credentials is not None, "accounts_count": 0}


@router.delete("/disconnect")
async def disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove ALL Google accounts for the current user.

    Equivalent of "disconnect Google entirely" — preferred for users who
    just want to revoke. To remove only one account, use DELETE /accounts/{id}.
    """
    rows = await db.execute(
        select(GoogleAccount).where(GoogleAccount.user_id == current_user.id)
    )
    for acc in rows.scalars():
        await db.delete(acc)
    current_user.google_credentials = None
    await db.commit()
    from app.services.credential_store import get_credential_store
    get_credential_store().clear(str(current_user.id))
    return {"message": "Google disconnected"}


@router.get("/app-config-status")
async def app_config_status():
    """Whether the shared Google OAuth app credentials are configured.
    Does not require authentication — used by the settings page to show
    setup instructions only when needed.
    """
    from app.services.system_config import get_config as gc
    s = get_settings()
    has_id     = bool(await gc("google_client_id",     fallback=s.google_client_id))
    has_secret = bool(await gc("google_client_secret", fallback=s.google_client_secret))
    return {"configured": has_id and has_secret}


# ── Setup wizard — save credentials from the UI ──────────────────────────────


class SaveAppConfigRequest(BaseModel):
    client_id: str = Field(..., min_length=1, description="OAuth Client ID from Google Cloud Console")
    client_secret: str = Field(..., min_length=1, description="OAuth Client Secret from Google Cloud Console")


@router.post("/app-config")
async def save_app_config(
    body: SaveAppConfigRequest,
    admin: User = Depends(require_admin),
):
    """Persist the Google OAuth client credentials so users can authenticate.

    Used by the in-app Setup Wizard. Admin only — these credentials are
    shared by the whole ELY install (every user OAuth flow uses them).
    Stored in the ``system_config`` table via ``set_config`` (encrypted
    at rest for the secret).
    """
    from app.services.system_config import set_config
    cid = body.client_id.strip()
    sec = body.client_secret.strip()
    if not cid or not sec:
        raise HTTPException(status_code=400, detail="client_id et client_secret requis")
    await set_config("google_client_id", cid, description="Google OAuth client ID (set via wizard)")
    await set_config("google_client_secret", sec, is_secret=True, description="Google OAuth client secret (set via wizard)")
    logger.info("Google OAuth app credentials updated by admin %s", admin.username)
    return {"configured": True}
