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

Admin-only (`require_admin`) endpoints :

  - `POST   /admin/learning/skill-creator/run`         (3.c)
        Trigger one full batch of create → eval → iterate for a user.

  - `GET    /admin/learning/skills/candidates`         (3.c)
        List candidate skills, filterable by status / user.

Phase 4.a — skill lifecycle :

  - `POST   /admin/learning/skills/{skill_id}/promote`
        Move a `candidate` skill to `active` (HITL promotion).
        Active skills get injected into the agent prompt (Phase 4.b).

  - `POST   /admin/learning/skills/{skill_id}/archive`
        Move an `active` or `stale` skill to `archived`. Recoverable.
        The curator (Phase 5) flips skills automatically too.

  - `POST   /admin/learning/skills/{skill_id}/restore`
        Move an `archived` skill back to `candidate` for re-review.

  - `DELETE /admin/learning/skills/{skill_id}`
        Permanently delete a `rejected` or `archived` skill. The
        underlying `failure_cases` rows are untouched (kept for
        forensic / future re-processing).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillStatus,
)
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
    # The body the admin reviews before promoting — promoting on name+score
    # alone would be flying blind. For a markdown_playbook it's the Markdown
    # body; for a python_tool (Sprint 4b V2) it's the generated Python source.
    # Capped server-side by the candidates `limit`, so payload size stays bounded.
    content: str
    # Sprint 4b V2 J8 — tells the review UI how to render `content`
    # (markdown_playbook → ReactMarkdown ; python_tool → code + validation report).
    content_format: str
    # Sprint 4b V2 J8 — JSON report from the 5-stage validation pipeline
    # (ast/ruff/mypy/smoke/registration). "{}" for markdown playbooks (they
    # don't go through it). The UI surfaces per-stage verdicts so the human
    # gate is informed, not a blind click.
    validation_report_json: str
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
            content=r.content,
            content_format=r.content_format,
            validation_report_json=r.validation_report_json,
            status=r.status,
            iteration_count=r.iteration_count,
            last_eval_score=r.last_eval_score,
            rationale=r.rationale,
            from_failure_case_ids=r.from_failure_case_ids,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


# ── Phase 4.a — lifecycle endpoints ────────────────────────────────────────


# Allowed status transitions. Anything not in here returns 409 Conflict.
# We model lifecycle on top of the enum so a future Phase 5 curator can
# transition active→stale and stale→archived without bypassing this map.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SkillStatus.CANDIDATE: {SkillStatus.ACTIVE, SkillStatus.ARCHIVED},
    SkillStatus.ACTIVE:    {SkillStatus.ARCHIVED, SkillStatus.STALE},
    SkillStatus.STALE:     {SkillStatus.ACTIVE, SkillStatus.ARCHIVED},
    SkillStatus.ARCHIVED:  {SkillStatus.CANDIDATE},  # restore back to review
    SkillStatus.REJECTED:  set(),                    # terminal, only DELETE
}


async def _load_skill_or_404(db: AsyncSession, skill_id: str) -> LearnedSkill:
    row = (await db.execute(
        select(LearnedSkill).where(LearnedSkill.id == skill_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Skill {skill_id!r} not found.")
    return row


async def _transition_status(
    db: AsyncSession,
    skill: LearnedSkill,
    new_status: str,
    *,
    admin_id: str,
) -> LearnedSkill:
    """Apply a status transition with the allowed-transitions check.

    Sets ``updated_at = now`` and persists. Does NOT commit — caller
    commits + reads ``skill`` back. Raises HTTPException 409 if the
    transition isn't allowed.
    """
    allowed = _ALLOWED_TRANSITIONS.get(skill.status, set())
    if new_status not in allowed:
        raise HTTPException(
            409,
            f"Transition {skill.status!r} → {new_status!r} not allowed. "
            f"Valid from {skill.status!r}: {sorted(allowed) or '(none — terminal)'}",
        )
    skill.status = new_status
    skill.updated_at = datetime.now(timezone.utc)
    return skill


def _invalidate_python_tool_cache(skill: LearnedSkill) -> None:
    """Sprint 4b V2 J7c — drop the per-user runtime cache after a status
    change that alters the user's *active* python_tool set (promote = now
    bindable, archive = no longer bindable). The cache never self-expires,
    so without this an archived tool would stay bound until restart. No-op
    for markdown playbooks (they don't go through the runtime loader).
    """
    if skill.content_format != SkillContentFormat.PYTHON_TOOL:
        return
    from app.services.learning import learned_tools_runtime
    learned_tools_runtime.invalidate(skill.user_id)


@router.post("/skills/{skill_id}/promote", response_model=CandidateOut)
async def promote_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """HITL admin promotion : `candidate` → `active`.

    Active skills get injected into the agent's system prompt at next
    turn (Phase 4.b wires the injection). This is the one moment a
    human reviews what the autonomous loop produced before it goes
    live for the user.
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status == SkillStatus.ACTIVE:
        # Idempotent — promoting an already-active skill is a no-op.
        return _to_candidate_out(skill)
    await _transition_status(db, skill, SkillStatus.ACTIVE, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    _invalidate_python_tool_cache(skill)
    logger.info(
        "skill_promoted: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


@router.post("/skills/{skill_id}/archive", response_model=CandidateOut)
async def archive_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """Move an `active` or `stale` skill to `archived`.

    Archived skills are hidden from the system prompt injection but
    kept in DB — restorable via `/restore`. The curator (Phase 5) does
    this automatically for skills unused too long.
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status == SkillStatus.ARCHIVED:
        return _to_candidate_out(skill)
    await _transition_status(db, skill, SkillStatus.ARCHIVED, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    _invalidate_python_tool_cache(skill)
    logger.info(
        "skill_archived: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


@router.post("/skills/{skill_id}/restore", response_model=CandidateOut)
async def restore_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """Move an `archived` skill back to `candidate` for re-review.

    Doesn't go straight to active — the admin must re-evaluate
    (possibly with fresh eyes) and explicitly re-promote.
    """
    skill = await _load_skill_or_404(db, skill_id)
    await _transition_status(db, skill, SkillStatus.CANDIDATE, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    logger.info(
        "skill_restored: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Permanently delete a `rejected` or `archived` skill.

    Active / candidate / stale skills must be archived first — this
    prevents accidental deletion of skills in use. The underlying
    `failure_cases` rows are NOT deleted (audit trail kept).
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status not in {SkillStatus.REJECTED, SkillStatus.ARCHIVED}:
        raise HTTPException(
            409,
            f"Cannot delete skill in status {skill.status!r}. "
            "Archive it first (active/stale → archived → delete).",
        )
    await db.execute(
        delete(LearnedSkill).where(LearnedSkill.id == skill_id)
    )
    await db.commit()
    logger.info(
        "skill_deleted: id=%s name=%s status_was=%s by_admin=%s",
        skill_id, skill.name, skill.status, admin.id[:8] if admin.id else "?",
    )
    return {"status": "deleted", "skill_id": skill_id}


def _to_candidate_out(skill: LearnedSkill) -> CandidateOut:
    return CandidateOut(
        id=skill.id,
        user_id=skill.user_id,
        name=skill.name,
        description=skill.description,
        content=skill.content,
        content_format=skill.content_format,
        validation_report_json=skill.validation_report_json,
        status=skill.status,
        iteration_count=skill.iteration_count,
        last_eval_score=skill.last_eval_score,
        rationale=skill.rationale,
        from_failure_case_ids=skill.from_failure_case_ids,
        created_at=skill.created_at.isoformat() if skill.created_at else "",
    )
