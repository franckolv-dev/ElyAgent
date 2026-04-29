# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/hitl_preference.py
# @brief      SQLAlchemy HitlPreference model — per-user HITL toggles
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""HitlPreference model — per-user, per-tool HITL on/off.

Default is "HITL ON" for every tool in ALWAYS_CRITICAL_TOOLS — this row
only exists when the user has explicitly toggled the preference. Absence
of a row means "use the system default" (= HITL on for critical tools).

Some tools are LOCKED at the UI level — they MUST always require HITL
regardless of the user's preference. These are the most destructive
operations (mass delete, SSH execute on prod servers, file system writes
outside permitted directories, vault unlock). The lock list lives in
``app/services/hitl_preferences.LOCKED_HITL_TOOLS`` and the UI grays out
the slider for those.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HitlPreference(Base):
    __tablename__ = "hitl_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_name", name="uq_hitl_pref_user_tool"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    requires_confirmation: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
