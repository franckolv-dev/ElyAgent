# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/onboarding.py
# @brief      REST API for the conversational onboarding flow.
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""REST API for the conversational onboarding flow.

Endpoints :
  - GET  /api/onboarding/status         → where is the user in the flow?
  - GET  /api/onboarding/next-question  → what to ask next? (or None if done)
  - POST /api/onboarding/answer         → submit user's answer to current Q
  - POST /api/onboarding/skip           → "Plus tard" (re-prompted next login)
  - POST /api/onboarding/restart        → reset progress, keep vocabulary
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import onboarding as onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class AnswerBody(BaseModel):
    question_id: str = Field(..., description="The id returned by /next-question. Anti-replay.")
    answer: str = Field(..., description="User's free-form answer.")


@router.get("/status")
async def status(current_user: User = Depends(get_current_user)) -> dict:
    return await onboarding_service.get_status(current_user.id)


@router.get("/next-question")
async def next_question(current_user: User = Depends(get_current_user)) -> dict:
    q = await onboarding_service.get_next_question(current_user.id)
    if q is None:
        return {"done": True, "question": None}
    return {"done": False, "question": q}


@router.post("/answer")
async def answer(body: AnswerBody, current_user: User = Depends(get_current_user)) -> dict:
    try:
        new_status = await onboarding_service.record_answer(
            current_user.id, body.question_id, body.answer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return new_status


@router.post("/skip")
async def skip(current_user: User = Depends(get_current_user)) -> dict:
    return await onboarding_service.skip_onboarding(current_user.id)


@router.post("/restart")
async def restart(current_user: User = Depends(get_current_user)) -> dict:
    return await onboarding_service.restart_onboarding(current_user.id)
