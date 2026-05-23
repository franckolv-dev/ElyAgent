# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/provider_switch.py
# @brief      Sprint 3.7 Jalon 1 — persisted provider fallback events.
#             Every time the chain falls over from primary to backup
#             LLM provider (FailoverReason enum).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.5.0
# =============================================================================
"""Persisted provider fallback events — Sprint 3.7 §2.4.

Until V1 of Sprint 3.7, these events lived only in the in-memory queue
`_pending_events[conversation_id]` of `fallback_manager.py:260`, drained
to a WebSocket toast, then forgotten. Now they survive : we can answer
"how often does DeepSeek pro time out ?" or "what's our actual
availability per provider over 30 days ?".

Retention : 30 days rolling (design note §8 — operational signal,
past stale data adds noise to current decisions).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderSwitch(Base):
    """One row per `provider.switched` event — Sprint 3.7 §2.4."""

    __tablename__ = "provider_switches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True)
    # LLM tier that switched ("A" | "B" | "C" | "IMG" | "MAINTENANCE")
    tier_llm: Mapped[str] = mapped_column(String(8))
    # Provider that failed (e.g. "deepseek-v4-pro")
    from_provider: Mapped[str] = mapped_column(String(64))
    # Provider that took over (e.g. "anthropic-sonnet")
    to_provider: Mapped[str] = mapped_column(String(64))
    # FailoverReason enum value : "rate_limit" | "billing" | "auth" | "timeout"
    # | "unavailable" | "empty_response" | "h1_hallucination" | "bad_request"
    # | "unknown"
    reason: Mapped[str] = mapped_column(String(32), index=True)
    # 1 = first failover, 2 = primary + 1st fallback both failed, ...
    position_in_chain: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
