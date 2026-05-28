# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/user_state.py
# @brief      Sprint 3 Jalon 1 — User State Vector.
#             One row per user holding a JSON state document refreshed
#             by the MAINTENANCE agent (Gemma 4 E4B local) at the end of
#             every conversation. Injected into the system prompt so
#             the agent always has a fresh snapshot of "where the user
#             is right now".
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.6.0
# =============================================================================
"""Per-user State Vector — Sprint 3 §3.

State shape (JSON, refreshed by MAINTENANCE LLM) ::

  {
    "mood":          str  — one-word affective tone, e.g. "focused", "stressed", "playful"
    "current_focus": str  — short phrase, e.g. "Sprint 3 + déménagement à Lyon"
    "recent_topics": list[str]  — last 5 distinct topics the user engaged with
    "open_loops":    list[str]  — unresolved threads ELY noticed (TODOs implicits)
    "energy_budget": str  — "high" | "normal" | "low" — proxy for how much ELY
                            should reach back vs. stay terse
  }

Retention : 1 row per user, **upsert in place** (state evolves, no history).
The Sprint 3.7 V1 signal tables already keep the historical audit trail.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserState(Base):
    """One row per user. ``state_json`` is the canonical document; helpers
    in ``app.services.learning.user_state`` handle (de)serialisation and
    default-value merging so callers never touch raw JSON."""

    __tablename__ = "user_states"

    # PK = user_id (one-to-one with users) so we can upsert by primary key
    # without a separate id column.
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), primary_key=True
    )
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    # sha256[:8] of the prompt active when this state was last refreshed —
    # lets the A/B testing machinery correlate state drift with prompt
    # changes (Sprint 3.7 §3.7.4).
    prompt_version: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, index=True
    )
