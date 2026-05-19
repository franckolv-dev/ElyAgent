# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/budget.py
# @brief      Budget API — read-only token / cost summary per user
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Budget API.

Tracking-only for now (Phase 5A). Returns aggregated token usage + estimated
cost over a period. No hard cap is enforced — the user monitors Qwen / Gemini
spend directly via their provider dashboard during the trial weeks.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.budget_guard import get_summary

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/summary")
async def summary(
    period: Literal["day", "week", "month"] = Query("day"),
    user: User = Depends(get_current_user),
):
    return await get_summary(user.id, period=period)
