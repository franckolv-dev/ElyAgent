# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/hitl_refusal.py
# @brief      Sprint 3.7 Jalon 1 — persisted HITL refusals.
#             User said "no" to an action ELY proposed (deny or ban).
#             First-class signal for auto-improvement (Sprint 3.7 §2.1).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Persisted HITL refusals — Sprint 3.7 §2.1.

Until V1 of Sprint 3.7, HITL refusals existed only in RAM (the
`HITLManager._PendingAction` dataclass, see hitl_manager.py:160), then
were dropped at end-of-turn. Now they survive : each row tells us
exactly which action the user rejected, against which tool, with what
arguments, under which prompt version.

Retention : permanent (design note §8 — explicit human signal, durable).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HitlRefusal(Base):
    """One row per `deny` or `ban` decision the user made on a proposed action."""

    __tablename__ = "hitl_refusals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True)
    # Mission this refusal occurred in, if any (refusals outside missions exist too)
    mission_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Name of the tool the agent was about to call, e.g. "gmail_trash_emails"
    tool_name: Mapped[str] = mapped_column(String(120), index=True)
    # JSON-serialized args with PII redacted by the anonymisation pipeline
    args_redacted: Mapped[str] = mapped_column(Text)
    # The action description the user actually saw and refused
    action_description: Mapped[str] = mapped_column(Text)
    # Decision : "deny" (one-shot refusal) or "ban" (refuse for the whole session)
    decision: Mapped[str] = mapped_column(String(16))
    # Why the refusal fired : "user-provided" (explicit click) or "timeout"
    # (no answer in N seconds, treated as refusal)
    reason: Mapped[str] = mapped_column(String(32))
    # LLM tier active when the action was proposed ("A" | "B" | "C" | "IMG")
    tier_llm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # sha256[:8] of the system prompt active at this turn — for A/B correlation
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Sprint 4d J1 — "learned" | "builtin" | NULL (pré-J1). Voir error_log.
    tool_origin: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
