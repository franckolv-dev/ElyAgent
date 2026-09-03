# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/arena.py
# @brief      Arena models -- blind side-by-side model comparison with ELO ranking.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Arena models -- blind side-by-side model comparison with ELO ranking."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArenaMatch(Base):
    """A single head-to-head comparison between two LLMs on one prompt."""

    __tablename__ = "arena_match"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, index=True)
    prompt: Mapped[str] = mapped_column(Text)

    # Labels formatted as "provider/model" (e.g. "anthropic/claude-sonnet-4-6")
    model_a: Mapped[str] = mapped_column(String(128), index=True)
    model_b: Mapped[str] = mapped_column(String(128), index=True)

    response_a: Mapped[str] = mapped_column(Text)
    response_b: Mapped[str] = mapped_column(Text)

    latency_a_ms: Mapped[int] = mapped_column(Integer, default=0)
    latency_b_ms: Mapped[int] = mapped_column(Integer, default=0)

    # vote: "a" | "b" | "tie" | "both_bad" | None (not yet voted)
    vote: Mapped[str | None] = mapped_column(String(16), nullable=True)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class ArenaElo(Base):
    """Per-model ELO rating (global, user-agnostic).

    The ELO rating of a model starts at 1000 and is updated after every vote
    using the standard Chess ELO formula with K=32.
    """

    __tablename__ = "arena_elo"

    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    elo: Mapped[float] = mapped_column(Float, default=1000.0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
