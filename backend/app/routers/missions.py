# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/missions.py
# @brief      REST API for the goal-driven Persistence Loop
# =============================================================================
"""REST API for the goal-driven Persistence Loop.

Endpoints :
  POST   /api/missions                         → create a mission (status=draft)
  GET    /api/missions                         → list user's missions
  GET    /api/missions/{id}                    → mission detail
  GET    /api/missions/{id}/steps              → audit trail
  GET    /api/missions/{id}/plan               → latest plan version
  POST   /api/missions/{id}/start              → draft|paused → planning + first tick
  POST   /api/missions/{id}/pause              → running → paused
  POST   /api/missions/{id}/abort              → kill switch (any → aborted)
  POST   /api/missions/{id}/tick               → manual tick (debug / testing)

PHASE 1 SCOPE — endpoints exist and return real DB data. The /start and
/tick paths run the SKELETON graph (returns a synthetic success). PHASE 2
will replace the graph nodes with real reasoning while keeping these
endpoints unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import mission_service

router = APIRouter(prefix="/api/missions", tags=["missions"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class MissionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    goal: str = Field(..., min_length=5)
    priority: int = Field(5, ge=1, le=10)
    budget_tokens: int = Field(50_000, ge=1000, le=500_000)
    budget_iterations: int = Field(30, ge=1, le=200)
    tick_interval_seconds: Optional[int] = Field(None, ge=30, le=86_400)
    deadline: Optional[datetime] = None


class MissionOut(BaseModel):
    id: str
    title: str
    goal: str
    status: str
    priority: int
    source: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    deadline: Optional[datetime]
    budget_tokens: int
    budget_iterations: int
    tokens_used: int
    iterations_used: int
    tick_interval_seconds: Optional[int]
    next_tick_at: Optional[datetime]
    final_summary: Optional[str]
    failure_reason: Optional[str]

    model_config = {"from_attributes": True}


class MissionStepOut(BaseModel):
    id: str
    iteration: int
    phase: str
    thought: Optional[str]
    tool_name: Optional[str]
    tool_input: Optional[dict]
    tool_output: Optional[str]
    evaluation: Optional[str]
    success: Optional[bool]
    tokens_used: int
    duration_ms: int
    model_used: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class MissionPlanOut(BaseModel):
    id: str
    version: int
    plan_text: str
    plan_json: Optional[dict]
    reason_for_replan: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AbortBody(BaseModel):
    reason: str = "User-requested abort"


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    body: MissionCreate,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    m = await mission_service.create_mission(
        user_id=current_user.id,
        title=body.title,
        goal=body.goal,
        priority=body.priority,
        source="ui",
        budget_tokens=body.budget_tokens,
        budget_iterations=body.budget_iterations,
        tick_interval_seconds=body.tick_interval_seconds,
        deadline=body.deadline,
    )
    return MissionOut.model_validate(m)


@router.get("", response_model=list[MissionOut])
async def list_missions(
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[MissionOut]:
    rows = await mission_service.list_missions_for_user(
        current_user.id, status=status_filter, limit=limit, offset=offset
    )
    return [MissionOut.model_validate(r) for r in rows]


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: str,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return MissionOut.model_validate(m)


@router.get("/{mission_id}/steps", response_model=list[MissionStepOut])
async def list_steps(
    mission_id: str,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
) -> list[MissionStepOut]:
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    rows = await mission_service.list_steps(mission_id, limit=limit)
    return [MissionStepOut.model_validate(r) for r in rows]


@router.get("/{mission_id}/plan", response_model=Optional[MissionPlanOut])
async def get_latest_plan(
    mission_id: str,
    current_user: User = Depends(get_current_user),
):
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    p = await mission_service.get_latest_plan(mission_id)
    return MissionPlanOut.model_validate(p) if p else None


# ── State transitions ───────────────────────────────────────────────────────

async def _own_or_404(mission_id: str, user: User):
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return m


@router.post("/{mission_id}/start", response_model=MissionOut)
async def start(mission_id: str, current_user: User = Depends(get_current_user)) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.start_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Phase 1 : we don't actually invoke the graph here yet.
    # Phase 2 : trigger an async task to run one tick of the graph.
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/pause", response_model=MissionOut)
async def pause(mission_id: str, current_user: User = Depends(get_current_user)) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.pause_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/abort", response_model=MissionOut)
async def abort(
    mission_id: str,
    body: AbortBody,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.abort_mission(mission_id, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/tick", response_model=dict)
async def tick(mission_id: str, current_user: User = Depends(get_current_user)) -> dict:
    """Run ONE iteration of the persistence loop (debug / manual trigger).

    Phase 1 : runs the SKELETON graph and returns the resulting state.
    Phase 2 : will be the same endpoint but with real planning/acting/eval.
    """
    m = await _own_or_404(mission_id, current_user)
    if m.status in {"completed", "failed", "aborted"}:
        raise HTTPException(status_code=400, detail=f"Mission est en état terminal ({m.status})")

    # Budget guard
    reason = await mission_service.check_budget(mission_id)
    if reason:
        await mission_service.fail_mission(mission_id, reason)
        raise HTTPException(status_code=400, detail=f"Budget dépassé : {reason}")

    # Compile graph with checkpointer
    from app.agent.missions.checkpointer import get_mission_checkpointer
    from app.agent.missions.graph import build_mission_graph

    cp = await get_mission_checkpointer()
    graph = build_mission_graph().compile(checkpointer=cp)

    # Ensure status reflects we're working
    if m.status == "draft":
        try:
            await mission_service.start_mission(mission_id)
        except ValueError:
            pass

    initial_state = {
        "mission_id": mission_id,
        "user_id": current_user.id,
        "goal": m.goal,
    }
    config = {"configurable": {"thread_id": mission_id}}

    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("Mission %s tick failed: %s", mission_id, exc)
        await mission_service.fail_mission(mission_id, f"graph error: {exc}")
        raise HTTPException(status_code=500, detail=f"Tick a échoué: {exc}")

    # Persist a step for audit (Phase 1: synthetic single step)
    await mission_service.add_step(
        mission_id, phase="eval",
        thought="Phase 1 skeleton tick",
        evaluation=result.get("last_eval_reason"),
        success=result.get("last_eval_success"),
        tokens_used=0,
        duration_ms=0,
        model_used=None,
    )

    # If the graph signaled done, complete the mission
    if result.get("done") and result.get("final_summary"):
        try:
            await mission_service.complete_mission(mission_id, result["final_summary"])
        except ValueError:
            # already terminal, ignore
            pass

    return {
        "iteration": result.get("iteration"),
        "plan_version": result.get("plan_version"),
        "done": bool(result.get("done")),
        "final_summary": result.get("final_summary"),
        "last_eval_success": result.get("last_eval_success"),
    }
