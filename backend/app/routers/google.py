"""Google OAuth2 endpoints — connect/disconnect Google services.

Each user has their own google_credentials stored in the users table.
The OAuth app credentials (client_id/secret) are shared and stored in
system_config (set via admin UI) or .env as fallback.
"""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.database import get_db, async_session
from app.models.user import User
from app.services.google_auth import build_auth_url, exchange_code

router = APIRouter(prefix="/google", tags=["google"])

# state → {"user_id": str, "code_verifier": str | None}
_pending_states: dict[str, dict] = {}


@router.get("/auth-url")
async def get_auth_url(current_user: User = Depends(get_current_user)):
    """Generate Google OAuth URL for the current user."""
    try:
        state = secrets.token_urlsafe(32)
        url, code_verifier = await build_auth_url(state)
        _pending_states[state] = {"user_id": current_user.id, "code_verifier": code_verifier}
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/callback")
async def oauth_callback(code: str, state: str):
    """Google redirects here after user consent. Stores tokens per user in DB."""
    pending = _pending_states.pop(state, None)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    user_id = pending["user_id"]
    code_verifier = pending.get("code_verifier")

    try:
        creds_dict = await exchange_code(code, code_verifier=code_verifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.google_credentials = json.dumps(creds_dict)
        await db.commit()

    s = get_settings()
    return RedirectResponse(url=f"{s.frontend_url}/settings?google=connected")


@router.get("/status")
async def get_status(current_user: User = Depends(get_current_user)):
    """Check Google connection status for the current user."""
    return {"connected": current_user.google_credentials is not None}


@router.delete("/disconnect")
async def disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove stored Google credentials for the current user."""
    current_user.google_credentials = None
    await db.commit()
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
