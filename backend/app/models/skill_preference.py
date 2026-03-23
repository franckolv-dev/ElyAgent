"""SkillPreference — per-user skill enable/disable settings.

One row per (user_id, skill_name) pair.  When no row exists for a skill,
the skill's ``enabled_by_default`` flag is used instead.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SkillPreference(Base):
    __tablename__ = "skill_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_name", name="uq_skill_pref_user_skill"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Optional JSON blob for per-skill configuration (e.g. API keys for 3rd-party skills)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
