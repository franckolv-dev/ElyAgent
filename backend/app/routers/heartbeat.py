# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/heartbeat.py
# @brief      Heartbeat API — opt-in autonomous self-check loop
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Heartbeat API.

Per-user opt-in for the autonomous heartbeat loop. The user controls:
- enabled (bool)
- interval (minutes, 1..1440)
- context (free-form markdown describing what to monitor)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.heartbeat_service import (
    schedule_heartbeat_for_user,
    unschedule_heartbeat_for_user,
)

router = APIRouter(prefix="/api/heartbeat", tags=["heartbeat"])


class HeartbeatSettings(BaseModel):
    enabled: bool
    interval_minutes: int = Field(30, ge=1, le=1440)
    context: str | None = ""


class HeartbeatStatus(BaseModel):
    enabled: bool
    interval_minutes: int
    context: str
    has_active_job: bool


@router.get("/", response_model=HeartbeatStatus)
async def get_heartbeat(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # The injected `user` may be a stale snapshot; re-read from this session
    # so we always return the latest committed state.
    result = await db.execute(select(User).where(User.id == user.id))
    fresh = result.scalar_one_or_none() or user
    from app.services.scheduler import get_scheduler
    has_job = bool(get_scheduler().get_job(f"heartbeat_{user.id}"))
    return HeartbeatStatus(
        enabled=fresh.heartbeat_enabled,
        interval_minutes=fresh.heartbeat_interval_minutes,
        context=fresh.heartbeat_context or "",
        has_active_job=has_job,
    )


@router.put("/", response_model=HeartbeatStatus)
async def update_heartbeat(
    body: HeartbeatSettings,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user.id))
    fresh = result.scalar_one_or_none()
    if not fresh:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    fresh.heartbeat_enabled = body.enabled
    fresh.heartbeat_interval_minutes = body.interval_minutes
    fresh.heartbeat_context = body.context or ""
    await db.commit()
    await db.refresh(fresh)

    if fresh.heartbeat_enabled:
        schedule_heartbeat_for_user(fresh)
    else:
        unschedule_heartbeat_for_user(fresh.id)

    from app.services.scheduler import get_scheduler
    has_job = bool(get_scheduler().get_job(f"heartbeat_{user.id}"))
    return HeartbeatStatus(
        enabled=fresh.heartbeat_enabled,
        interval_minutes=fresh.heartbeat_interval_minutes,
        context=fresh.heartbeat_context or "",
        has_active_job=has_job,
    )


@router.post("/run-now")
async def run_now(user: User = Depends(get_current_user)):
    """Trigger one heartbeat tick immediately (useful for testing the context)."""
    from app.services.heartbeat_service import _execute_heartbeat
    import asyncio
    asyncio.create_task(_execute_heartbeat(user.id))
    return {"message": "Heartbeat lancé en arrière-plan"}
