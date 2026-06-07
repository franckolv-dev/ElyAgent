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

  - `POST   /admin/learning/tool-creator/run`          (Sprint 4b V2)
        Trigger one python_tool generate → validate (5 stages) → persist
        loop. The V2 analogue of skill-creator/run (Markdown playbooks).

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

import json
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
from app.services.learning.learned_tools_runtime import python_tools_enabled
from app.services.learning.tool_creator import generate_and_persist_tool

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


class ToolCreatorRunRequest(BaseModel):
    """Sprint 4b V2 — trigger one python_tool generation loop."""

    task_description: str = Field(
        ...,
        min_length=8,
        description=(
            "Plain-language description of the tool to generate. Be explicit "
            "about the signature when it matters, e.g. 'compute the n-th "
            "Fibonacci number — fibonacci(n: int) -> int'."
        ),
    )
    user_id: str = Field(
        ...,
        description=(
            "User the generated python_tool is scoped to "
            "(every LearnedSkill is user-scoped)."
        ),
    )
    smoke_kwargs: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Optional sample kwargs to exercise the function in the smoke "
            "sandbox stage (e.g. {\"n\": 10}). Omit to skip smoke — the other "
            "4 validation stages still run."
        ),
    )
    max_iterations: int = Field(
        3,
        ge=1,
        le=5,
        description=(
            "Cap on generate→validate retries; the failing stage's error is "
            "fed back into the next generation. Default 3."
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


class ToolGapOut(BaseModel):
    """A capability ELY's `find_tool` searched for but couldn't surface — the
    `tool_absent_acknowledged` signal (find_tool Phase 2). The admin reviews
    these, decides if it's worth generating a new tool (→ /tool-creator/run)
    or marks it processed to clear the queue."""

    id: int
    user_id: str
    # The natural-language capability the user/model asked for (extracted from
    # the FailureCase replay_payload).
    capability: str
    conversation_id: Optional[str]
    mission_id: Optional[str]
    created_at: str
    # ISO timestamp when an admin (or the auto-pipeline, later) marked this
    # gap as handled. None while the gap is still open.
    processed_at: Optional[str]
    # If the gap was resolved by generating a learned skill, its id is kept
    # here so the UI can link to the candidate page.
    learned_skill_id: Optional[str]


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


@router.post("/tool-creator/run")
async def run_tool_creator(
    body: ToolCreatorRunRequest,
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Sprint 4b V2 — trigger one python_tool generate→validate→persist loop.

    The V2 analogue of `/skill-creator/run` (which produces V1 Markdown
    playbooks). Admin-only. Calls the tier-S LLM (`LLM_TIER_S_CHAIN`) to
    write a PURE python_tool, runs the 5-stage validation pipeline
    (ast → ruff → mypy → smoke → registration), and on success persists a
    `candidate` LearnedSkill (`content_format=python_tool`) for review on the
    candidates page and HITL promotion.

    NEVER auto-activates — promotion stays a human gate, and the tool only
    becomes bindable once promoted AND `LEARNED_PYTHON_TOOLS_ENABLED` is on.
    The response echoes `python_tools_enabled` so the caller knows whether a
    promoted tool would actually go live.
    """
    try:
        summary = await generate_and_persist_tool(
            task_description=body.task_description,
            user_id=body.user_id,
            smoke_kwargs=body.smoke_kwargs,
            max_iterations=body.max_iterations,
        )
    except Exception as exc:
        # generate_and_persist_tool is built to never raise; this is
        # belt-and-braces so a surprise still yields a clean 500.
        logger.exception("tool_creator run crashed for user_id=%s", body.user_id)
        raise HTTPException(500, f"tool_creator orchestrator crashed: {exc}")
    summary["python_tools_enabled"] = python_tools_enabled()
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


# ── tool_absent gaps — find_tool Phase 2 outcomes ──────────────────────────


def _tool_gap_to_out(row) -> ToolGapOut:
    """Build a ToolGapOut from a FailureCase row (signal_table=tool_absent).

    `capability` is extracted from the replay_payload JSON (where Phase 2 puts
    it). Falls back to `expected_outcome` (the truncated capability also kept
    in a dedicated column for indexing).
    """
    capability = row.expected_outcome or ""
    try:
        payload = json.loads(row.replay_payload or "{}")
        capability = payload.get("capability") or capability
    except (ValueError, TypeError):
        pass
    return ToolGapOut(
        id=row.id,
        user_id=row.user_id,
        capability=capability,
        conversation_id=row.conversation_id,
        mission_id=row.mission_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
        processed_at=row.processed_at.isoformat() if row.processed_at else None,
        learned_skill_id=row.learned_skill_id,
    )


@router.get("/tool-gaps")
async def list_tool_gaps(
    status: str = Query(
        "open",
        description="Filter: 'open' (default — unprocessed gaps) or 'all'.",
    ),
    user_id: Optional[str] = Query(None, description="Filter to one user."),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ToolGapOut]:
    """List capability gaps recorded by find_tool Phase 2.

    Each row is a unique capability the user/model asked for but the catalog
    couldn't satisfy (record_tool_absent dedupes on the capability fingerprint
    while still unprocessed, so no row inflation).
    """
    if status not in {"open", "all"}:
        raise HTTPException(400, f"Unknown status {status!r}. Valid: open, all")

    from app.models.failure_case import FailureCase

    query = select(FailureCase).where(FailureCase.signal_table == "tool_absent")
    if status == "open":
        query = query.where(FailureCase.processed_at.is_(None))
    if user_id:
        query = query.where(FailureCase.user_id == user_id)
    query = query.order_by(FailureCase.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [_tool_gap_to_out(r) for r in rows]


class ToolGapMarkProcessedRequest(BaseModel):
    """Optional body for /tool-gaps/{id}/mark-processed.

    Both fields are optional: pass `learned_skill_id` to record which skill
    resolved this gap (links gap → candidate in the UI). `reason` is a free
    note (e.g. "out of scope", "duplicate") kept for auditability.
    """

    learned_skill_id: Optional[str] = None
    reason: Optional[str] = None


@router.post("/tool-gaps/{gap_id}/mark-processed", response_model=ToolGapOut)
async def mark_tool_gap_processed(
    gap_id: int,
    body: Optional[ToolGapMarkProcessedRequest] = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ToolGapOut:
    """Mark a `tool_absent` gap as handled — sets processed_at=now().

    Idempotent: a gap already processed simply returns its current state.
    Pass `learned_skill_id` if the gap was resolved by generating a candidate
    (links the gap to the candidate page).
    """
    from app.models.failure_case import FailureCase

    row = (await db.execute(
        select(FailureCase).where(
            FailureCase.id == gap_id,
            FailureCase.signal_table == "tool_absent",
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"tool_absent gap {gap_id} not found")
    if row.processed_at is None:
        row.processed_at = datetime.now(timezone.utc)
        if body and body.learned_skill_id:
            row.learned_skill_id = body.learned_skill_id
        await db.commit()
        await db.refresh(row)
        logger.info("tool_gap_processed: id=%s by_admin=%s skill=%s",
                    row.id, _admin.id[:8] if _admin.id else "?",
                    row.learned_skill_id or "—")
    return _tool_gap_to_out(row)
