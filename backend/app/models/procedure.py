# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/procedure.py
# @brief      Procedural memory — successful tool-call sequences ELY learns
#             from past missions and can replay or adapt.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""Procedural memory store — Sprint 2.5.

One row = one mission's reusable how-to. Granularity rule (design note §8):
**1 mission = 1 procedure** (we don't store per-step micro-procedures).

`tool_calls` is the serialized JSON list of tool invocations that solved the
mission, in execution order. The maintenance agent (Sprint 2.5 §4) decides
which missions are worth promoting to a procedure and writes here explicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Procedure(Base):
    """Reusable tool-call sequence learned from a past successful mission."""

    __tablename__ = "procedures"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_procedures_user_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    # Stable human-readable identifier — e.g. "find-duplicate-photos-in-drive"
    slug: Mapped[str] = mapped_column(String(120))
    # Natural-language intent the procedure satisfies — used for semantic recall
    intent: Mapped[str] = mapped_column(Text)
    # Ordered JSON list of {"tool": str, "args": {...}, "result_summary": str}
    tool_calls: Mapped[str] = mapped_column(Text)
    # Origin mission id, for traceability
    source_mission_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # How many times this procedure has been recalled (Sprint 2.5 V2 — dreaming-style scoring)
    recall_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # How many times the procedure was replayed and succeeded
    success_count: Mapped[int] = mapped_column(Integer, default=1)
    # Last time this procedure was recalled or replayed
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # True when migration heuristic was unsure about classification (audit trail)
    migrated_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
