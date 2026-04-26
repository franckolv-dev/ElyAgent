# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/feedback.py
# @brief      User feedback on assistant responses — used for Phase 2 SLM/LLM routing refinement.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""User feedback on assistant responses — used for Phase 2 SLM/LLM routing refinement."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, index=True)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    # The user message text (truncated) — embedded in Phase 2 for similarity search
    user_message: Mapped[str] = mapped_column(Text)
    # 1 = thumbs up (correct tier), -1 = thumbs down (wrong tier)
    rating: Mapped[int] = mapped_column(Integer)
    # Which model handled the request: "slm:qwen2.5:3b-instruct" or "llm:claude-..."
    model_used: Mapped[str] = mapped_column(String(128))
    # Raw IntentRouter score (0-100) at the time of routing
    routing_score: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
