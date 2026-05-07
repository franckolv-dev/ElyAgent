# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/licence.py
# @brief      Licence activation + status endpoints
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# =============================================================================
"""Licence routes.

* ``GET  /api/licence/status``         — current state, any authed user.
* ``POST /api/licence/activate-free``  — admin only, click-wrap consent.
* ``POST /api/licence/activate-paid``  — admin only, paste licence key.

There is no demo / trial endpoint — the free tier (4 users) is the
evaluation path. Customers needing more buy a paid licence directly.

Every successful activation writes one ``AuditLog`` row through
``app.services.audit_log.audit`` (best-effort, fire-and-forget).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models.user import User
from app.services.audit_log import audit
from app.services.licence_service import (
    activate_free_tier,
    activate_paid_tier,
    get_licence_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/licence", tags=["licence"])


# ── Request schemas ──────────────────────────────────────────────────────────


class ActivateFreeRequest(BaseModel):
    consent: bool = Field(
        ...,
        description="Must be true — confirms strictly private, non-commercial use.",
    )


class ActivatePaidRequest(BaseModel):
    tier: str = Field(..., description="pro | business | enterprise")
    licence_key: str = Field(..., min_length=1)
    customer_label: str = Field(..., min_length=1, max_length=200)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status")
async def licence_status(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current licence state.

    Any authenticated user can read this — the banner uses it to decide
    whether to display warnings.  No sensitive data (the raw licence key)
    is exposed.
    """
    return await get_licence_status(db)


@router.post("/activate-free", status_code=status.HTTP_201_CREATED)
async def licence_activate_free(
    req: ActivateFreeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        licence = await activate_free_tier(
            db, admin_user_id=admin.id, consent=req.consent
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()

    await audit(
        admin.id,
        "licence.activate.free",
        details=f"tier=free, customer_label={licence.customer_label}",
    )
    return await get_licence_status(db)


@router.post("/activate-paid", status_code=status.HTTP_201_CREATED)
async def licence_activate_paid(
    req: ActivatePaidRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        licence = await activate_paid_tier(
            db,
            admin_user_id=admin.id,
            tier=req.tier,
            licence_key=req.licence_key,
            customer_label=req.customer_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()

    await audit(
        admin.id,
        "licence.activate.paid",
        details=(
            f"tier={licence.tier}, customer_label={licence.customer_label}, "
            f"key_len={len(licence.licence_key or '')}"
        ),
    )
    return await get_licence_status(db)
