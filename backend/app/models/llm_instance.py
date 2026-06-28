# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/llm_instance.py
# @brief      LLM instances — named provider+model combinations stored in DB.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""LLM instances — named provider+model combinations stored in DB."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LLMInstance(Base):
    """A named LLM instance: provider + model + optional API key + label.

    Multiple instances can be created for the same provider (e.g. several
    Ollama models) and assigned freely to routing tiers via their UUID.
    """
    __tablename__ = "llm_instances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    label: Mapped[str] = mapped_column(String(255))
    # "ollama" | "anthropic" | "gemini" | "deepseek" | "mistral" | "zhipu" | "openrouter"
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(255))
    # Stored in plain text for now (SQLite local DB), masked as "***" in API responses.
    # None for Ollama (no key needed).
    api_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
