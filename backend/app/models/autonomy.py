"""Durable event automations and per-mission assurance, scoped to their owner."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(32))
    account: Mapped[str] = mapped_column(String(160), default="default")
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    goal: Mapped[str] = mapped_column(Text)
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=5)
    cursor_json: Mapped[str] = mapped_column(Text, default="{}")
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    __table_args__ = (UniqueConstraint("rule_id", "event_key", name="uq_automation_event"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String, ForeignKey("automation_rules.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    mission_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class MissionAssurance(Base):
    __tablename__ = "mission_assurance"
    mission_id: Mapped[str] = mapped_column(String, ForeignKey("missions.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    results_json: Mapped[str] = mapped_column(Text, default="[]")
    waiting_for: Mapped[str | None] = mapped_column(String(32), nullable=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutonomyPreferences(Base):
    __tablename__ = "autonomy_preferences"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    rules_json: Mapped[str] = mapped_column(Text, default="{}")
    notifications: Mapped[str] = mapped_column(String(20), default="important")


class ProcedureTrial(Base):
    __tablename__ = "procedure_trials"
    __table_args__ = (UniqueConstraint("skill_id", "run_key", name="uq_procedure_trial"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str] = mapped_column(String, ForeignKey("learned_skills.id", ondelete="CASCADE"), index=True)
    run_key: Mapped[str] = mapped_column(String(160))
    outcome: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ActionReceipt(Base):
    """An execution reservation survives a crash; uncertain writes require review."""

    __tablename__ = "autonomy_action_receipts"
    __table_args__ = (UniqueConstraint("mission_id", "action_key", name="uq_mission_action"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    mission_id: Mapped[str] = mapped_column(String, ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action_key: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(160))
    effect: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="started")
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
