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
    # Sprint 4c J1 (2026-06-10) — spec structurée V2 (YAML : steps + foreach
    # + handlers on_*). NULL = mission legacy « prompt monolithe » (goal
    # seul), rétrocompatibilité totale. Voir services/mission_spec.py pour
    # le contrat, et la révision Alembic 0002 pour la migration.
    spec_yaml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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

    # Reports de tick sur panne PASSAGÈRE du fournisseur LLM (429, 5xx,
    # délai dépassé). Une limite de débit n'est pas un bug : elle se résout
    # en attendant, et tuer la mission jetterait son travail (31/08/2026).
    # Borné par MAX_PROVIDER_RETRIES, remis à zéro au premier tick réussi.
    provider_retries: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
    )

    # ── Autonomous mode (2026-06-04) ──
    # When True the loop auto-approves HITL for NON-floor tools so an
    # unattended (e.g. 3 a.m.) run doesn't stall waiting for a confirmation
    # nobody answers. Floor tools (irreversible / external / security —
    # security_filter.NEVER_AUTONOMOUS_TOOLS) are still NOT auto-approved.
    autonomous: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Mandat d'autonomie (Missions autonomes J1, 2026-07-11) ──
    # NULL = mission sans mandat (supervisée) — rétrocompat totale.
    # `mandate_json` est la forme CANONIQUE (mission_spec.mandate_to_json :
    # défauts appliqués, clés triées) figée à la création — c'est ELLE que
    # J2 lira pour l'enforcement, pas le YAML brut. `autonomy_state` trace
    # le cycle de vie du mandat (J1 : 'pending_validation' ; validation
    # HITL + activation en J2/J6). Distinct du booléen `autonomous`
    # ci-dessus (auto-approve léger 2026-06-04) : le mandat est le grant
    # déclaratif complet. Révision Alembic 0018.
    mandate_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    autonomy_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # J3 — snapshot de la dernière pause disjoncteur (JSON : paused_at, reason,
    # counters, thresholds). Trace conservée après reprise ; le CARNET (J4)
    # la rend lisible. NULL = jamais pausée par un disjoncteur. Révision 0019.
    autonomy_pause_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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


class MissionStepRun(Base):
    """Sprint 4c J2 — statut d'exécution d'un step de spec structurée,
    par item quand le step a un ``foreach``.

    C'est la matière première du viewer (J4) :

        ✓ read_companies        done
        ⏳ enrich_company       5/47
             ✓ Acme Corp        done — Jean Dupont, jean@acme.fr
             ⏸ Gamma SARL       waiting_user — 3 résultats, lequel ?
             ⊝ Delta Industries skipped — Entreprise introuvable

    Un step sans foreach a UNE ligne (item_index=0, item_value NULL).
    Statuts : pending / running / done / skipped / waiting_user / failed.
    """
    __tablename__ = "mission_step_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String, ForeignKey("missions.id", ondelete="CASCADE"), index=True,
    )
    step_id: Mapped[str] = mapped_column(String(64), index=True)

    item_index: Mapped[int] = mapped_column(Integer, default=0)
    item_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # skip reason / question ask_user / message d'erreur — affiché tel quel
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # extrait du résultat (done) — nourrit le viewer et les steps suivants
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Sprint 4c J3 — réponse de l'utilisateur à une question ask_user.
    # Injectée au prompt acteur quand l'item est retraité ; conservée
    # ensuite (audit : « pourquoi l'agent a fait ce choix »).
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_mission_step_runs_lookup", "mission_id", "step_id", "item_index", unique=True),
    )


class MissionDailyCounter(Base):
    """Compteurs journaliers d'une mission autonome (Missions autonomes J3).

    PERSISTÉS (pas en mémoire) : un restart backend ne réinitialise pas le
    compteur du jour — les seuils D4 restent honnêtes. Une ligne par
    (mission, jour UTC). ``*_ack`` = seuil acquitté par l'utilisateur
    (« continuer ») → plus de re-prompt ce jour-là pour ce compteur."""
    __tablename__ = "mission_daily_counters"

    mission_id: Mapped[str] = mapped_column(String, ForeignKey("missions.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD UTC
    tool_actions: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_ack: Mapped[bool] = mapped_column(Boolean, default=False)
