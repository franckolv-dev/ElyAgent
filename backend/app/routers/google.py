"""Google OAuth2 endpoints — connect/disconnect Google services."""
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

# In-memory store for state tokens (maps state → user_id)
# In production, use Redis or DB-backed storage
_pending_states: dict[str, str] = {}


@router.get("/auth-url")
async def get_auth_url(current_user: User = Depends(get_current_user)):
    """Generate Google OAuth URL. Frontend redirects user here."""
    try:
        state = secrets.token_urlsafe(32)
        _pending_states[state] = current_user.id
        url = build_auth_url(state)
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/callback")
async def oauth_callback(code: str, state: str):
    """Google redirects here after user consent. Stores tokens in DB."""
    user_id = _pending_states.pop(state, None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    try:
        creds_dict = exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.google_credentials = json.dumps(creds_dict)
        await db.commit()

    # Redirect to settings page after successful connection
    s = get_settings()
    frontend = s.frontend_url
    return RedirectResponse(url=f"{frontend}/settings?google=connected")


@router.get("/status")
async def get_status(current_user: User = Depends(get_current_user)):
    """Check if the current user has connected Google."""
    return {"connected": current_user.google_credentials is not None}


@router.delete("/disconnect")
async def disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke and remove stored Google credentials."""
    current_user.google_credentials = None
    await db.commit()
    return {"message": "Google disconnected"}
