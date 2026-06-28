# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/arena.py
# @brief      Arena REST API -- blind side-by-side LLM comparison + ELO leaderboard
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
"""Arena REST API -- blind side-by-side LLM comparison + ELO leaderboard.

POST   /api/arena/match        run a new blind match (2 models, same prompt)
POST   /api/arena/vote         record the user's vote and update ELO
GET    /api/arena/leaderboard  read the global ELO leaderboard
GET    /api/arena/history      read the user's recent matches
GET    /api/arena/models       list models currently available in the pool
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import arena_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/arena", tags=["arena"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MatchIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    model_a: str | None = None
    model_b: str | None = None


class VoteIn(BaseModel):
    match_id: str
    vote: str = Field(..., pattern=r"^(a|b|tie|both_bad)$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/models")
async def list_models(current_user: User = Depends(get_current_user)):
    """List models currently usable in the Arena (depends on configured keys)."""
    return {"models": arena_service.list_available_models()}


@router.post("/match", status_code=status.HTTP_201_CREATED)
async def create_match(
    payload: MatchIn,
    current_user: User = Depends(get_current_user),
):
    try:
        force = None
        if payload.model_a and payload.model_b:
            force = (payload.model_a, payload.model_b)
        result = await arena_service.run_match(
            prompt=payload.prompt,
            user_id=str(current_user.id),
            force_models=force,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Arena match %s: user=%s %s vs %s",
        result["match_id"], current_user.id, result["model_a"], result["model_b"],
    )
    return result


@router.post("/vote")
async def vote(
    payload: VoteIn,
    current_user: User = Depends(get_current_user),
):
    try:
        result = await arena_service.record_vote(
            match_id=payload.match_id,
            user_id=str(current_user.id),
            vote=payload.vote,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Arena vote: user=%s match=%s vote=%s",
        current_user.id, payload.match_id, payload.vote,
    )
    return result


@router.get("/leaderboard")
async def leaderboard(current_user: User = Depends(get_current_user)):
    return {"leaderboard": await arena_service.leaderboard()}


@router.get("/history")
async def history(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 100))
    return {"matches": await arena_service.match_history(str(current_user.id), limit)}
