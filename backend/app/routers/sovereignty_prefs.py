# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/sovereignty_prefs.py
# @brief      REST API for the PII-sovereignty toggle.
# @license    Elastic License 2.0
# =============================================================================
"""Per-user PII-sovereignty preference.

A single boolean :
- ``sovereignty_strict`` — when True, every tier-B/C cloud call is routed
  to the EU Mistral chain (Large → Medium → Small) instead of the user's
  default cloud provider (typically DeepSeek). Tiers SIMPLE / MAINTENANCE
  are unaffected (already local) ; IMAGE is unaffected (separate path).
  Off by default ; opt-in via Settings.

Endpoints :
- ``GET   /api/preferences/sovereignty`` — read the current state
- ``PATCH /api/preferences/sovereignty`` — update the flag

The toggle reads from ``User.sovereignty_strict``. The runtime side picks
it up via ``app.services.sovereignty.SOVEREIGNTY_STRICT`` (a ContextVar set
by the chat/voice/telegram entry points at the start of each turn).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class SovereigntyPrefsOut(BaseModel):
    sovereignty_strict: bool
    # Surface whether a Mistral instance is actually configured. If False
    # while strict=True, the UI shows a warning: the toggle is honoured but
    # there's no EU provider to route to → graceful fallback to default chain.
    mistral_configured: bool


class SovereigntyPrefsPatch(BaseModel):
    """All fields optional — PATCH semantics."""

    sovereignty_strict: bool | None = None


def _mistral_configured() -> bool:
    """True if at least one Mistral instance is registered (any of L/M/S)."""
    try:
        from app.services.sovereignty import get_sovereign_provider_ids
        return bool(get_sovereign_provider_ids())
    except Exception:  # noqa: BLE001
        return False


@router.get("/sovereignty", response_model=SovereigntyPrefsOut)
async def get_sovereignty_prefs(
    current_user: User = Depends(get_current_user),
) -> SovereigntyPrefsOut:
    """Return the current user's PII-sovereignty preference."""
    return SovereigntyPrefsOut(
        sovereignty_strict=bool(getattr(current_user, "sovereignty_strict", False)),
        mistral_configured=_mistral_configured(),
    )


@router.patch("/sovereignty", response_model=SovereigntyPrefsOut)
async def update_sovereignty_prefs(
    body: SovereigntyPrefsPatch,
    current_user: User = Depends(get_current_user),
) -> SovereigntyPrefsOut:
    """Update the PII-sovereignty preference. Returns the post-update state."""
    async with async_session() as db:
        row = await db.execute(select(User).where(User.id == current_user.id))
        user = row.scalar_one()
        if body.sovereignty_strict is not None:
            user.sovereignty_strict = bool(body.sovereignty_strict)
            logger.info(
                "sovereignty_strict updated: user=%s value=%s",
                current_user.id[:8] if current_user.id else "?",
                user.sovereignty_strict,
            )
        await db.commit()
        await db.refresh(user)
        return SovereigntyPrefsOut(
            sovereignty_strict=bool(user.sovereignty_strict),
            mistral_configured=_mistral_configured(),
        )
