# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/hallucination_block.py
# @brief      Sprint 3.7 Jalon 1 — persisted hallucination blocks.
#             Every time completion_guard rewrites a response because the
#             model claimed a destructive action it never executed.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""Persisted hallucination blocks — Sprint 3.7 §2.2.

Each row matches one `completion_guard` rewrite trigger (see
`app/services/completion_guard.py`). The `GuardVerdict` dataclass is
already structured (matched_patterns, tools_invoked, reason), we just
make it durable so A/B testing can measure "did variant B halluciate
less than variant A on prompt_version XYZ".

Retention : 90 days rolling (design note §8 — volume potentially high
if a model misbehaves systematically).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HallucinationBlock(Base):
    """One row per completion_guard rewrite — Sprint 3.7 §2.2."""

    __tablename__ = "hallucination_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True)
    mission_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Concrete model identifier, e.g. "deepseek-v4-pro" or "gemma-4-e4b-it"
    model_used: Mapped[str] = mapped_column(String(120))
    # LLM tier active at the time ("A" | "B" | "C" | "IMG" | "MAINTENANCE").
    # Nullable — at the call site (chat.py:612) the tier isn't always
    # trivially reachable, so we accept NULL rather than fake a value.
    tier_llm: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    # JSON array of regex pattern keys that matched (e.g. ["fr.passive_past"])
    matched_patterns: Mapped[str] = mapped_column(Text)
    # JSON array of tool names actually invoked in the turn (may be empty)
    tools_invoked: Mapped[str] = mapped_column(Text)
    # JSON array of destructive tools invoked (subset of tools_invoked)
    destructive_tools_invoked: Mapped[str] = mapped_column(Text)
    # Machine-friendly reason key, e.g. "completion_claim_without_destructive_tool_call"
    reason: Mapped[str] = mapped_column(String(120))
    # The original (pre-rewrite) model response, truncated to 1000 chars
    original_response: Mapped[str] = mapped_column(Text)
    # sha256[:8] of the system prompt active at this turn
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
