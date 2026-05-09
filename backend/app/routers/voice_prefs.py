# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/app/routers/voice_prefs.py
# @brief      REST API for per-user voice / TTS preferences
# =============================================================================
"""Per-user voice / TTS preferences.

Currently a single toggle :
- ``tts_auto_enabled`` — should the avatar read agent replies aloud
  automatically ? Default True (legacy behaviour). Persists across page
  reloads.

Endpoints :
- ``GET   /api/preferences/voice`` — read the current state
- ``PATCH /api/preferences/voice`` — update one or more fields

Why a separate router rather than a generic « preferences » blob ?
HITL preferences already live in /hitl/preferences and have a different
shape (one row per tool). Keeping voice prefs scoped here means we can
grow the surface (output voice, rate, language hint, transcript echo)
without colliding with HITL or onboarding state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.user import User

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class VoicePrefsOut(BaseModel):
    tts_auto_enabled: bool


class VoicePrefsPatch(BaseModel):
    """All fields optional — PATCH semantics."""
    tts_auto_enabled: bool | None = None


@router.get("/voice", response_model=VoicePrefsOut)
async def get_voice_prefs(
    current_user: User = Depends(get_current_user),
) -> VoicePrefsOut:
    """Return the current user's voice preferences."""
    return VoicePrefsOut(
        tts_auto_enabled=bool(current_user.tts_auto_enabled),
    )


@router.patch("/voice", response_model=VoicePrefsOut)
async def update_voice_prefs(
    body: VoicePrefsPatch,
    current_user: User = Depends(get_current_user),
) -> VoicePrefsOut:
    """Update one or more voice preferences. Returns the post-update state."""
    async with async_session() as db:
        # Re-fetch the user inside this session so we can mutate it cleanly.
        row = await db.execute(select(User).where(User.id == current_user.id))
        user = row.scalar_one()
        if body.tts_auto_enabled is not None:
            user.tts_auto_enabled = bool(body.tts_auto_enabled)
        await db.commit()
        await db.refresh(user)
        return VoicePrefsOut(tts_auto_enabled=bool(user.tts_auto_enabled))
