# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/mission.py
# @brief      Mission models — goal-driven persistence loop state
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Mission models — goal-driven persistence loop state.

A *Mission* is a long-running, goal-driven task that ELY pursues across
multiple iterations of a Plan → Act → Eval → Replan loop. It survives
backend restarts (LangGraph SqliteSaver checkpointer) and accumulates a
full audit trail (`MissionStep`) plus a versioned plan (`MissionPlan`).

Three tables :
  - missions            : the goal + metadata + budgets + status
  - mission_plans       : versioned plan trees (one row per replan)
  - mission_steps       : every iteration of the loop (audit trail)

Key design decisions :
  - status is an explicit string enum (not Python Enum) so SQLite migrations
    stay trivial — Alembic isn't configured, schema is created via
    `Base.metadata.create_all` at startup.
  - tokens / iterations budgets are SOFT in the DB (just numeric caps),
    enforced by the loop itself before each LLM call.
  - the LangGraph state is stored separately in
    `data/missions_checkpoints.sqlite` (managed by AsyncSqliteSaver) using
    `mission.id` as `thread_id`. We don't duplicate it in the SQL DB; this
    table is the *user-visible* metadata, the checkpointer is the
    *engine-internal* state machine memory.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Status enum (string-typed for SQLite simplicity) ──────────────────────────
# draft     : created, not yet started
# planning  : agent is building/refining the plan
# running   : agent is executing steps
# paused    : paused by user (can be resumed)
# completed : goal achieved, final summary written
# failed    : terminal failure (budget exhausted, fatal tool error, etc.)
# aborted   : explicitly killed by user

MISSION_STATUSES = {"draft", "planning", "running", "paused", "completed", "failed", "aborted"}
MISSION_TERMINAL_STATUSES = {"completed", "failed", "aborted"}

MISSION_SOURCES = {"ui", "scheduled_task", "channel", "autonomous"}

STEP_PHASES = {"plan", "act", "eval", "replan", "hitl_wait"}


class Mission(Base):
    """A goal-driven mission tracked across iterations."""
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    # ── User-facing description ──
    title: Mapped[str] = mapped_column(String(255))
    goal: Mapped[str] = mapped_column(Text)  # the actual objective the agent pursues

    # ── Lifecycle ──
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1=highest, 10=lowest
    source: Mapped[str] = mapped_column(String(20), default="ui")  # ui / scheduled_task / channel / autonomous
    source_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # FK-ish (scheduled_task.id, conversation.id…)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Sprint 3.7 Jalon 4 — set by the LLM-as-judge cron (mission_critic.py)
    # once a terminal mission has been critiqued, so subsequent ticks skip
    # it (`run_pending_critiques` filters WHERE critic_run_at IS NULL).
    # The column was created at startup via database.py's ALTER TABLE and
    # is queried/written by mission_critic.py, but was never declared on
    # this model — so `Mission.critic_run_at` raised AttributeError on
    # every cron tick (every 5 min). Declaring it here closes the gap.
    critic_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ── Guard rails (enforced by the loop) ──
    budget_tokens: Mapped[int] = mapped_column(Integer, default=50_000)
    budget_iterations: Mapped[int] = mapped_column(Integer, default=30)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    iterations_used: Mapped[int] = mapped_column(Integer, default=0)

    # ── Heartbeat config (cron-like) ──
    # null = single-shot, runs until completion. set = recurring tick.
    tick_interval_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    next_tick_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # ── Final state ──
    final_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Relationships ──
    plans: Mapped[list["MissionPlan"]] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="MissionPlan.version",
    )
    steps: Mapped[list["MissionStep"]] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="MissionStep.iteration",
    )

    __table_args__ = (
        Index("ix_missions_user_status", "user_id", "status"),
        Index("ix_missions_next_tick", "next_tick_at"),
    )


class MissionPlan(Base):
    """A versioned plan for a mission. New version = replan event."""
    __tablename__ = "mission_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id: Mapped[str] = mapped_column(String, ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Free-form markdown for human readability ("- [ ] Task 1\n- [x] Task 2…")
    plan_text: Mapped[str] = mapped_column(Text)
    # Structured plan for the agent: list of {id, description, status, depends_on}
    plan_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    reason_for_replan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # null for v1
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    mission: Mapped["Mission"] = relationship(back_populates="plans")


class MissionStep(Base):
    """One iteration of the Plan→Act→Eval→Replan loop. Audit trail."""
    __tablename__ = "mission_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id: Mapped[str] = mapped_column(String, ForeignKey("missions.id", ondelete="CASCADE"), index=True)

    iteration: Mapped[int] = mapped_column(Integer)  # 1, 2, 3… per mission
    phase: Mapped[str] = mapped_column(String(20))   # plan / act / eval / replan / hitl_wait

    # ── Action context (when phase=act) ──
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Agent's reasoning trace (always populated) ──
    thought: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Evaluation verdict (when phase=eval)
    evaluation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # ── Telemetry ──
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Sprint 3.7 Jalon 3 — sha256[:8] of the system prompt active when this
    # step ran. Lets analysts correlate step success/failure rates with
    # specific prompt versions when A/B testing lands (Jalon 5).
    prompt_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    mission: Mapped["Mission"] = relationship(back_populates="steps")

    __table_args__ = (
        Index("ix_mission_steps_mission_iter", "mission_id", "iteration"),
    )
