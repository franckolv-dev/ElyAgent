# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_service.py
# @brief      Mission CRUD + lifecycle helpers
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Mission CRUD + lifecycle helpers.

Thin wrapper around the ORM that the rest of the codebase (router,
mission_graph, scheduler) uses to manipulate missions without touching
SQLAlchemy directly. Keeps state-machine transitions in one place.

Design notes :
  - All transition methods (`start`, `pause`, `complete`, `fail`, `abort`)
    validate the source status to prevent illegal moves
    (e.g. you can't `complete` a `draft` — it must go through `running`).
  - Budget guards live HERE, not in the LangGraph nodes — keeps the graph
    pure (each node just runs, the supervisor decides when to stop).
  - Never log the full goal text in INFO logs — goals can contain emails,
    phone numbers, internal project names. Only IDs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.mission import (
    Mission, MissionPlan, MissionStep,
    MISSION_STATUSES, MISSION_TERMINAL_STATUSES, MISSION_SOURCES, STEP_PHASES,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Creation ─────────────────────────────────────────────────────────────────

async def create_mission(
    user_id: str,
    title: str,
    goal: str,
    *,
    priority: int = 5,
    source: str = "ui",
    source_ref: Optional[str] = None,
    budget_tokens: int = 50_000,
    budget_iterations: int = 30,
    tick_interval_seconds: Optional[int] = None,
    deadline: Optional[datetime] = None,
) -> Mission:
    """Create a new mission in `draft` status."""
    if source not in MISSION_SOURCES:
        raise ValueError(f"invalid source: {source!r}")

    mission = Mission(
        user_id=user_id,
        title=title.strip()[:255] or "Sans titre",
        goal=goal.strip(),
        status="draft",
        priority=priority,
        source=source,
        source_ref=source_ref,
        budget_tokens=budget_tokens,
        budget_iterations=budget_iterations,
        tick_interval_seconds=tick_interval_seconds,
        deadline=deadline,
    )
    async with async_session() as db:
        db.add(mission)
        await db.commit()
        await db.refresh(mission)
    logger.info("Mission created id=%s user=%s priority=%d", mission.id, user_id, priority)
    return mission


# ── State transitions ───────────────────────────────────────────────────────

async def _transition(mission_id: str, *, from_: set[str], to: str, **fields) -> Mission:
    """Atomic status transition with optimistic source-status check.

    Raises ValueError if the mission isn't in one of the allowed `from_`
    states (prevents illegal transitions like complete→draft).
    """
    async with async_session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
        if not m:
            raise ValueError(f"mission {mission_id!r} not found")
        if m.status not in from_:
            raise ValueError(
                f"cannot transition mission {mission_id!r} from status {m.status!r} to {to!r}"
            )
        m.status = to
        for k, v in fields.items():
            setattr(m, k, v)
        await db.commit()
        await db.refresh(m)
        logger.info("Mission %s: %s → %s", mission_id, [s for s in from_][0] if len(from_) == 1 else "(any)", to)
        return m


async def start_mission(mission_id: str) -> Mission:
    """draft|paused → planning. Marks `started_at` if first start."""
    fields = {}
    async with async_session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
        if m and m.started_at is None:
            fields["started_at"] = _utcnow()
    return await _transition(mission_id, from_={"draft", "paused"}, to="planning", **fields)


async def mark_running(mission_id: str) -> Mission:
    """planning → running (first plan finalized)."""
    return await _transition(mission_id, from_={"planning"}, to="running")


async def pause_mission(mission_id: str) -> Mission:
    """running|planning → paused."""
    return await _transition(mission_id, from_={"running", "planning"}, to="paused")


async def complete_mission(mission_id: str, summary: str) -> Mission:
    """running → completed."""
    return await _transition(
        mission_id, from_={"running"}, to="completed",
        completed_at=_utcnow(), final_summary=summary,
    )


async def fail_mission(mission_id: str, reason: str) -> Mission:
    """any-non-terminal → failed."""
    return await _transition(
        mission_id, from_={"draft", "planning", "running", "paused"}, to="failed",
        completed_at=_utcnow(), failure_reason=reason,
    )


async def abort_mission(mission_id: str, reason: str = "User-requested abort") -> Mission:
    """any-non-terminal → aborted (kill switch)."""
    return await _transition(
        mission_id, from_={"draft", "planning", "running", "paused"}, to="aborted",
        completed_at=_utcnow(), failure_reason=reason,
    )


# ── Read helpers ────────────────────────────────────────────────────────────

async def get_mission(mission_id: str) -> Optional[Mission]:
    async with async_session() as db:
        return (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()


async def list_missions_for_user(
    user_id: str,
    *,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Mission]:
    async with async_session() as db:
        q = select(Mission).where(Mission.user_id == user_id)
        if status:
            q = q.where(Mission.status == status)
        q = q.order_by(Mission.created_at.desc()).limit(limit).offset(offset)
        return list((await db.execute(q)).scalars().all())


async def list_due_missions(now: Optional[datetime] = None) -> list[Mission]:
    """Missions whose `next_tick_at` ≤ now and that are still active.

    Used by the heartbeat to know which missions need a tick.
    """
    now = now or _utcnow()
    async with async_session() as db:
        q = (
            select(Mission)
            .where(Mission.status.in_({"running", "planning"}))
            .where(Mission.next_tick_at.isnot(None))
            .where(Mission.next_tick_at <= now)
            .order_by(Mission.priority.asc(), Mission.next_tick_at.asc())
        )
        return list((await db.execute(q)).scalars().all())


# ── Plan operations ─────────────────────────────────────────────────────────

async def add_plan(
    mission_id: str,
    plan_text: str,
    plan_json: Optional[dict] = None,
    reason_for_replan: Optional[str] = None,
) -> MissionPlan:
    """Append a new plan version. Auto-increments `version`."""
    async with async_session() as db:
        # Compute next version number
        result = await db.execute(
            select(func.max(MissionPlan.version)).where(MissionPlan.mission_id == mission_id)
        )
        max_version = result.scalar() or 0
        plan = MissionPlan(
            mission_id=mission_id,
            version=max_version + 1,
            plan_text=plan_text,
            plan_json=plan_json,
            reason_for_replan=reason_for_replan,
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
    logger.info("Mission %s: plan v%d added (%d chars)", mission_id, plan.version, len(plan_text))
    return plan


async def get_latest_plan(mission_id: str) -> Optional[MissionPlan]:
    async with async_session() as db:
        q = (
            select(MissionPlan)
            .where(MissionPlan.mission_id == mission_id)
            .order_by(MissionPlan.version.desc())
            .limit(1)
        )
        return (await db.execute(q)).scalar_one_or_none()


# ── Step operations ─────────────────────────────────────────────────────────

async def add_step(
    mission_id: str,
    phase: str,
    *,
    thought: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_input: Optional[dict] = None,
    tool_output: Optional[str] = None,
    evaluation: Optional[str] = None,
    success: Optional[bool] = None,
    tokens_used: int = 0,
    duration_ms: int = 0,
    model_used: Optional[str] = None,
) -> MissionStep:
    """Append a new step to the audit trail. Auto-numbers `iteration`."""
    if phase not in STEP_PHASES:
        raise ValueError(f"invalid phase: {phase!r} (allowed: {STEP_PHASES})")

    async with async_session() as db:
        # Compute next iteration number (per mission)
        result = await db.execute(
            select(func.max(MissionStep.iteration)).where(MissionStep.mission_id == mission_id)
        )
        max_iter = result.scalar() or 0

        step = MissionStep(
            mission_id=mission_id,
            iteration=max_iter + 1,
            phase=phase,
            thought=thought,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            evaluation=evaluation,
            success=success,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            model_used=model_used,
        )
        db.add(step)

        # Concurrently bump the mission's running counters
        await db.execute(
            update(Mission)
            .where(Mission.id == mission_id)
            .values(
                tokens_used=Mission.tokens_used + tokens_used,
                iterations_used=Mission.iterations_used + 1,
            )
        )
        await db.commit()
        await db.refresh(step)
    return step


async def list_steps(mission_id: str, *, limit: int = 200) -> list[MissionStep]:
    async with async_session() as db:
        q = (
            select(MissionStep)
            .where(MissionStep.mission_id == mission_id)
            .order_by(MissionStep.iteration.asc())
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())


# ── Budget guards (called by the loop before each LLM call) ─────────────────

async def check_budget(mission_id: str) -> Optional[str]:
    """Return a failure reason string if mission is out of budget, else None.

    Caller is expected to `fail_mission` with the returned reason if non-null.
    """
    m = await get_mission(mission_id)
    if not m:
        return "mission not found"
    if m.iterations_used >= m.budget_iterations:
        return f"iteration budget exhausted ({m.iterations_used}/{m.budget_iterations})"
    if m.tokens_used >= m.budget_tokens:
        return f"token budget exhausted ({m.tokens_used}/{m.budget_tokens})"
    if m.deadline and _utcnow() > m.deadline:
        return f"deadline exceeded ({m.deadline.isoformat()})"
    return None
