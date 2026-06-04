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
    autonomous: bool = False


class MissionUpdate(BaseModel):
    """Editable mission fields — all optional, only provided ones change.

    Allowed only when the mission is NOT actively executing (see
    ``_EDIT_BLOCKED_STATES``). Lets the user fix the goal, bump the
    iteration budget, change the tick schedule, etc. and re-run, instead
    of delete + recreate.
    """

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    goal: Optional[str] = Field(None, min_length=5)
    priority: Optional[int] = Field(None, ge=1, le=10)
    budget_tokens: Optional[int] = Field(None, ge=1000, le=500_000)
    budget_iterations: Optional[int] = Field(None, ge=1, le=200)
    tick_interval_seconds: Optional[int] = Field(None, ge=30, le=86_400)
    deadline: Optional[datetime] = None
    autonomous: Optional[bool] = None


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
    autonomous: bool
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
        autonomous=body.autonomous,
    )
    return MissionOut.model_validate(m)


# Mission states where editing parameters is unsafe (it's actively running).
_EDIT_BLOCKED_STATES = {"planning", "running"}


@router.patch("/{mission_id}", response_model=MissionOut)
async def update_mission(
    mission_id: str,
    body: MissionUpdate,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    """Edit a mission's parameters (goal, budgets, tick schedule, …) without
    deleting + recreating it.

    Blocked while the mission is actively executing (planning/running) —
    pause it or wait for it to finish first (409). Only the fields present
    in the request body change. After editing, /restart (resets counters)
    then /start to re-run with the new params.
    """
    m = await _own_or_404(mission_id, current_user)
    if m.status in _EDIT_BLOCKED_STATES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Mission en cours ({m.status}) — mets-la en pause ou attends "
                "la fin avant de l'éditer."
            ),
        )

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return MissionOut.model_validate(m)

    from datetime import datetime as _dt, timezone as _tz

    from app.database import async_session
    from app.models.mission import Mission

    async with async_session() as db:
        fresh = await db.get(Mission, mission_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        for key, value in fields.items():
            setattr(fresh, key, value)
        fresh.updated_at = _dt.now(_tz.utc)
        await db.commit()
        await db.refresh(fresh)
        result = MissionOut.model_validate(fresh)

    from app.services.audit_log import audit
    await audit(
        current_user.id, "mission_edit",
        details=",".join(fields.keys())[:200], command=mission_id, channel="web",
    )
    return result


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
    # Mark the mission for immediate pickup by the heartbeat loop.
    # Without this the heartbeat would wait `tick_interval_seconds` (or
    # forever for single-shot missions) before the first tick.
    from app.services.mission_heartbeat import schedule_first_tick
    await schedule_first_tick(mission_id)
    # Audit trail (mai 2026 — Admin → Logs visibility)
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_start",
                details=(getattr(m, "title", None) or "")[:200],
                command=mission_id, channel="web")
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/pause", response_model=MissionOut)
async def pause(mission_id: str, current_user: User = Depends(get_current_user)) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.pause_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_pause",
                details=(getattr(m, "title", None) or "")[:200],
                command=mission_id, channel="web")
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
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_abort",
                details=(body.reason or "")[:200],
                command=mission_id, channel="web")
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

    # Note : the nodes themselves persist MissionStep rows (plan/act/eval/replan).
    # We don't double-log here. We only handle the terminal transition.

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


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    mission_id: str,
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a mission, its plan and its steps.

    Allowed regardless of mission state — useful for cleaning up failed
    missions stuck in the list (e.g. after a code-level crash like the
    `langgraph.checkpoint.sqlite` import error of April 2026). The mission's
    LangGraph checkpoint state is also cleared via thread_id.
    """
    m = await _own_or_404(mission_id, current_user)

    # Remove any LangGraph checkpoint persisted under this mission's thread_id
    # so a future mission with the same id doesn't inherit stale state. This
    # is best-effort — failures here don't block the DB delete.
    try:
        from app.agent.missions.graph import build_mission_graph
        graph = build_mission_graph()
        config = {"configurable": {"thread_id": mission_id}}
        # AsyncSqliteSaver exposes adelete_thread on recent versions
        ckpt = getattr(graph, "checkpointer", None)
        if ckpt is not None and hasattr(ckpt, "adelete_thread"):
            try:
                await ckpt.adelete_thread(mission_id)
            except Exception:
                pass
    except Exception:
        pass

    # Delete cascades : MissionPlan + MissionStep rows have FK on mission_id.
    # We do explicit deletes in case CASCADE isn't declared on every relation.
    from app.database import async_session
    from app.models.mission import Mission, MissionPlan, MissionStep
    from sqlalchemy import delete as _sqldel
    async with async_session() as db:
        await db.execute(_sqldel(MissionStep).where(MissionStep.mission_id == mission_id))
        await db.execute(_sqldel(MissionPlan).where(MissionPlan.mission_id == mission_id))
        await db.execute(_sqldel(Mission).where(Mission.id == mission_id))
        await db.commit()
    return None  # 204 No Content


class _RestartBody(BaseModel):
    """Optional fresh budgets for the restarted mission."""
    max_iterations: int | None = None
    max_tokens: int | None = None
    keep_history: bool = False  # if False (default) plan + steps wiped, if True kept


@router.post("/{mission_id}/restart", response_model=MissionOut)
async def restart(
    mission_id: str,
    body: _RestartBody | None = None,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    """Reset a mission to ``draft`` status so it can be started again.

    Useful when a mission failed (e.g. due to a transient bug like a missing
    Python module) and the user wants to retry without re-typing the title +
    goal + budgets.

    Default behaviour : wipe plan history + steps so the next ``start`` produces
    a fresh plan. Pass ``keep_history=true`` if you want the previous plan
    kept for reference (rare).
    """
    body = body or _RestartBody()
    m = await _own_or_404(mission_id, current_user)

    from app.database import async_session
    from app.models.mission import Mission, MissionPlan, MissionStep
    from sqlalchemy import delete as _sqldel
    from datetime import datetime, timezone

    async with async_session() as db:
        if not body.keep_history:
            await db.execute(_sqldel(MissionStep).where(MissionStep.mission_id == mission_id))
            await db.execute(_sqldel(MissionPlan).where(MissionPlan.mission_id == mission_id))

        fresh = await db.get(Mission, mission_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Mission not found")

        fresh.status = "draft"
        fresh.failure_reason = None
        fresh.iterations_used = 0
        fresh.tokens_used = 0
        fresh.started_at = None
        fresh.completed_at = None
        fresh.next_tick_at = None
        fresh.final_summary = None
        fresh.updated_at = datetime.now(timezone.utc)
        if body.max_iterations is not None:
            fresh.budget_iterations = max(1, body.max_iterations)
        if body.max_tokens is not None:
            fresh.budget_tokens = max(100, body.max_tokens)
        await db.commit()
        await db.refresh(fresh)

    # Also wipe the LangGraph checkpoint so the next start doesn't replay
    # the previous terminal state. Without this, a mission that had reached
    # 'completed' in its checkpoint will be re-marked completed on the very
    # first tick after restart (no real work performed). The previous
    # implementation called `build_mission_graph()` without compiling, which
    # always returned `checkpointer=None` — so the deletion never ran.
    try:
        from app.agent.missions.checkpointer import get_mission_checkpointer
        cp = await get_mission_checkpointer()
        if cp is not None and hasattr(cp, "adelete_thread"):
            await cp.adelete_thread(mission_id)
            logger.info("Mission checkpoint wiped for %s", mission_id[:8])
    except Exception as _exc:
        logger.warning("Mission checkpoint wipe failed for %s: %s", mission_id[:8], _exc)

    return MissionOut.model_validate(fresh)
