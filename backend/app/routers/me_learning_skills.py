# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/me_learning_skills.py
# @brief      Sprint 4b Phase 5.b — user-facing endpoints for learned skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""User-facing learning skills endpoints — Sprint 4b Phase 5.b.

The /admin/learning/skills/* endpoints (Phase 4.a) are admin-only.
This router exposes a smaller, USER-scoped surface so each user can
inspect what ELY has learned about THEM and exercise some control :

  - `GET    /api/me/learning-skills`         — list MY skills
  - `POST   /api/me/learning-skills/{id}/pin` — toggle pin (curator bypass)
  - `POST   /api/me/learning-skills/{id}/forget` — archive (always
                                                   recoverable by admin)

Cross-user safety
-----------------
Every endpoint checks `skill.user_id == current_user.id` before
mutating or returning anything. A user CANNOT pin or forget another
user's skill, even with the right id (404, not 403, so the existence
of the row isn't leaked).

Differences from the admin router
---------------------------------
- No `promote` — that's a HITL admin decision (Phase 4.a).
- No `restore` / `delete` — users can only archive ("forget"). Admins
  retain the full lifecycle controls.
- No filtering by user_id (always implied by the JWT) or by status
  (we return ALL statuses so the user sees the whole picture).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.learned_skill import LearnedSkill, SkillStatus
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me/learning-skills", tags=["learning"])


# ── Response model ─────────────────────────────────────────────────────────


class MeSkillOut(BaseModel):
    id: str
    name: str
    description: str
    content: str            # full body — users get progressive disclosure too
    status: str
    source: str
    iteration_count: int
    last_eval_score: Optional[int]
    pinned: bool
    use_count: int
    last_used_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    model_config = {"from_attributes": True}


def _to_out(s: LearnedSkill) -> MeSkillOut:
    return MeSkillOut(
        id=s.id,
        name=s.name,
        description=s.description,
        content=s.content,
        status=s.status,
        source=s.source,
        iteration_count=s.iteration_count,
        last_eval_score=s.last_eval_score,
        pinned=bool(s.pinned),
        use_count=s.use_count,
        last_used_at=s.last_used_at.isoformat() if s.last_used_at else None,
        created_at=s.created_at.isoformat() if s.created_at else None,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
    )


async def _load_skill_or_404(
    db: AsyncSession, skill_id: str, user_id: str,
) -> LearnedSkill:
    """Load a skill, enforce ownership, 404 (not 403) on mismatch so the
    foreign skill's existence isn't leaked across users."""
    row = (await db.execute(
        select(LearnedSkill).where(
            LearnedSkill.id == skill_id,
            LearnedSkill.user_id == user_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Skill introuvable.")
    return row


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[MeSkillOut])
async def list_my_skills(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MeSkillOut]:
    """Return every LearnedSkill the calling user owns, all statuses.

    Ordered by status priority (active first, then stale, candidate,
    archived, rejected) then by use_count desc — most relevant first.
    """
    rows = (await db.execute(
        select(LearnedSkill)
        .where(LearnedSkill.user_id == user.id)
        .order_by(
            # Status priority via CASE — SQLite-friendly
            LearnedSkill.status,
            LearnedSkill.use_count.desc(),
            LearnedSkill.updated_at.desc(),
        )
    )).scalars().all()
    return [_to_out(r) for r in rows]


class PinRequest(BaseModel):
    pinned: bool


@router.post("/{skill_id}/pin", response_model=MeSkillOut)
async def pin_skill(
    skill_id: str,
    body: PinRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeSkillOut:
    """Toggle the pin flag on the calling user's skill.

    A pinned skill bypasses the auto-curator (Phase 5.a) — even if
    unused for years, it stays active. Use this to "freeze" a
    high-value playbook the agent rarely needs but you want to keep
    instantly available.
    """
    skill = await _load_skill_or_404(db, skill_id, user.id)
    skill.pinned = bool(body.pinned)
    skill.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(skill)
    logger.info(
        "skill_pin_toggled: id=%s name=%s pinned=%s by_user=%s",
        skill.id, skill.name, skill.pinned,
        user.id[:8] if user.id else "?",
    )
    return _to_out(skill)


@router.post("/{skill_id}/forget", response_model=MeSkillOut)
async def forget_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeSkillOut:
    """Move the skill to `archived`. Always reversible by admin.

    Semantics : the user says "stop using this playbook on me". The
    skill is hidden from the system prompt (active/stale → archived)
    but the underlying `failure_cases` rows are KEPT so the skill
    creator can re-process the pattern in the future if it surfaces
    again.

    Already-archived or rejected skills are no-op (200 with current
    state). The admin endpoint /admin/learning/skills/{id}/delete is
    the only path to permanent removal.
    """
    skill = await _load_skill_or_404(db, skill_id, user.id)
    if skill.status in (SkillStatus.ARCHIVED, SkillStatus.REJECTED):
        # No-op : already invisible to the agent.
        return _to_out(skill)
    skill.status = SkillStatus.ARCHIVED
    skill.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(skill)
    logger.info(
        "skill_forgotten: id=%s name=%s by_user=%s",
        skill.id, skill.name, user.id[:8] if user.id else "?",
    )
    return _to_out(skill)
