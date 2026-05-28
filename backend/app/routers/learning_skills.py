# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/learning_skills.py
# @brief      Sprint 4b Phase 3.c — admin endpoints for the skill_creator loop
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Admin endpoints for the autonomous skill-creation loop.

Two endpoints, both admin-only (`require_admin`) :

  - `POST /admin/learning/skill-creator/run`
        Trigger one full batch of create → eval → iterate for a given user.
        Returns the orchestrator's structured summary.

  - `GET  /admin/learning/skills/candidates`
        List candidate `LearnedSkill` rows with their iteration count,
        last eval score, and rationale. Lets the admin review before
        promoting to `active` (Phase 4 will add the promotion endpoint).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.learned_skill import LearnedSkill, SkillStatus
from app.models.user import User
from app.services.learning.skill_iteration import MAX_ITERATIONS
from app.services.learning.skill_orchestrator import run_full_loop

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/learning", tags=["learning"])


# ── Request / response schemas ──────────────────────────────────────────────


class SkillCreatorRunRequest(BaseModel):
    user_id: str = Field(
        ...,
        description=(
            "The user whose failure_cases the creator should process. "
            "Required: every LearnedSkill is user-scoped."
        ),
    )
    batch_size: int = Field(
        3,
        ge=1,
        le=10,
        description=(
            "How many failure-pattern clusters to process this run. "
            "Each cluster becomes at most one candidate skill."
        ),
    )
    max_iterations: int = Field(
        MAX_ITERATIONS,
        ge=1,
        le=MAX_ITERATIONS,
        description=(
            "Cap on patch attempts per candidate before marking it "
            "rejected. Default = MAX_ITERATIONS (5)."
        ),
    )


class CandidateOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    status: str
    iteration_count: int
    last_eval_score: Optional[int]
    rationale: Optional[str]
    from_failure_case_ids: str  # JSON string
    created_at: str

    model_config = {"from_attributes": True}


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/skill-creator/run")
async def run_skill_creator(
    body: SkillCreatorRunRequest,
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Trigger one full batch of skill creation + eval + iteration.

    Admin-only. Synchronous : the call blocks until the orchestrator
    is done with the batch (which can take 30-60 s per cluster with
    Opus + 1-5 evaluations). Returns the structured summary so the
    admin can see what happened in one round trip.
    """
    try:
        summary = await run_full_loop(
            user_id=body.user_id,
            batch_size=body.batch_size,
            max_iterations=body.max_iterations,
        )
    except Exception as exc:
        # The orchestrator is built to never raise, but if it does
        # we want a clean 500 instead of letting the stack trace
        # bubble up to the user.
        logger.exception(
            "skill_creator run crashed for user_id=%s", body.user_id,
        )
        raise HTTPException(500, f"skill_creator orchestrator crashed: {exc}")
    return summary


@router.get("/skills/candidates")
async def list_candidates(
    user_id: Optional[str] = Query(
        None,
        description="Filter to one user. Omit to list across all users.",
    ),
    status: Optional[str] = Query(
        None,
        description=(
            "Filter by status (candidate | active | stale | archived "
            "| rejected). Default = candidate (the ones awaiting "
            "promotion review)."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CandidateOut]:
    """List `LearnedSkill` rows for admin review.

    Default filter is `status=candidate` because that's what the
    promotion UI (Phase 4) will display. Pass `?status=rejected` to
    audit the failure tail or `?status=active` to see what's live.
    """
    target_status = status or SkillStatus.CANDIDATE
    if target_status not in SkillStatus.ALL:
        raise HTTPException(
            400,
            f"Unknown status {target_status!r}. Valid: {sorted(SkillStatus.ALL)}",
        )

    query = select(LearnedSkill).where(LearnedSkill.status == target_status)
    if user_id:
        query = query.where(LearnedSkill.user_id == user_id)
    query = query.order_by(LearnedSkill.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [
        CandidateOut(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            description=r.description,
            status=r.status,
            iteration_count=r.iteration_count,
            last_eval_score=r.last_eval_score,
            rationale=r.rationale,
            from_failure_case_ids=r.from_failure_case_ids,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
