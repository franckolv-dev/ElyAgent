# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/feedback.py
# @brief      Feedback router — thumbs up / down on assistant responses
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Feedback router — thumbs up / down on assistant responses.

Stored in SQLite for Phase 2: embedding-based routing adjustment.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.feedback import Feedback
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackIn(BaseModel):
    conversation_id: str
    user_message: str = Field(..., max_length=1000)
    rating: int = Field(..., ge=-1, le=1)          # 1 = 👍, -1 = 👎  (0 not used)
    model_used: str = Field(default="llm", max_length=128)
    routing_score: int = Field(default=50, ge=0, le=100)


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackIn,
    current_user: User = Depends(get_current_user),
):
    if payload.rating == 0:
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")

    # Sprint 3.7 Jalon 3 — capture the active system prompt version so the
    # rating can be aggregated per prompt variant when A/B testing lands.
    try:
        from app.services.learning import current_system_prompt_version
        prompt_version = current_system_prompt_version()
    except Exception:
        prompt_version = None

    async with async_session() as db:
        fb = Feedback(
            user_id=str(current_user.id),
            conversation_id=payload.conversation_id,
            user_message=payload.user_message[:500],
            rating=payload.rating,
            model_used=payload.model_used,
            routing_score=payload.routing_score,
            prompt_version=prompt_version,
        )
        db.add(fb)
        await db.commit()
        logger.info(
            "Feedback saved: user=%s conv=%s rating=%d model=%s score=%d",
            current_user.id, payload.conversation_id, payload.rating,
            payload.model_used, payload.routing_score,
        )

    return {"status": "ok", "id": fb.id}
