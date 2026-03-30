# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""User memory models — episodic logs and consolidated profile.

UserMemoryLog : Raw episodic facts captured during conversations (short-term memory).
UserProfile   : Consolidated, clean user profile built from logs (long-term memory).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserMemoryLog(Base):
    """Raw episodic facts captured during conversations — short-term memory."""

    __tablename__ = "user_memory_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # e.g. "User is working on Python agent project named ELY"
    fact: Mapped[str] = mapped_column(Text)
    # "preference" | "context" | "event" | "skill" | "personal"
    fact_type: Mapped[str] = mapped_column(String(32), default="context")
    # Absolute timestamp when the fact was first observed
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # Whether this log has been processed by the consolidation job
    is_consolidated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class UserProfile(Base):
    """Consolidated, clean user profile — long-term memory.

    Each row is a single key/value fact about a user.  A unique constraint on
    (user_id, key) ensures there is at most one entry per fact type per user.
    """

    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_profiles_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    # e.g. "main_project", "preferred_language", "expertise_level", "timezone"
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    # 0.0–1.0 — decreases when the value is contradicted by new evidence
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # How many distinct log entries contributed to this fact
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    # None = permanent fact; set for time-limited facts (e.g. "working on deadline in 2 weeks")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
