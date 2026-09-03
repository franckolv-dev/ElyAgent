# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/user_vocabulary.py
# @brief      Personal vocabulary mappings learned during onboarding.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Personal vocabulary mappings.

Each row maps a term used by THIS user to the canonical term Éli should
internally substitute. Examples :

  user_term="mes mailings"     domain="gmail"     canonical_term="newsletters"
  user_term="boulot"           domain="calendar"  canonical_term="Travail Pro"
  user_term="ELY-Test"         domain="gmail"     canonical_term="ELY-Test"  (custom label, kept as-is)
  user_term="Franky"           domain="general"   canonical_term="(forme courte du prénom)"

Populated by the onboarding flow (`app/services/onboarding.py`) and read
when building the system prompt at every chat/mission turn so the agent
naturally understands the user's wording.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserVocabulary(Base):
    __tablename__ = "user_vocabulary"
    __table_args__ = (
        # No two identical (user_id, user_term, domain) entries — keeps
        # the table tidy and the lookup deterministic.
        UniqueConstraint("user_id", "user_term", "domain", name="uq_user_vocab_term"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    user_term: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_term: Mapped[str] = mapped_column(String(200), nullable=False)
    examples: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # 1.0 = explicitly stated by user, 0.7 = inferred from a screenshot/heuristic.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    learned_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
