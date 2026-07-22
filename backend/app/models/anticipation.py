# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/anticipation.py
# @brief      C5 — suggestions d'anticipation (récurrence détectée → proposer)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""AnticipationSuggestion — C5 V1 (mode suggestion, cadrage validé 22/07).

Une row = « tu me demandes X régulièrement — veux-tu en faire une tâche
planifiée ? ». Ely PROPOSE, l'humain dispose : la ligne ne déclenche
jamais rien d'elle-même. Une suggestion par ``pattern_hash`` maximum ;
un refus (``dismissed``) est définitif — le détecteur ne re-propose
jamais le même pattern (anti-spam par simple existence de la row).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SuggestionStatus:
    """proposed → accepted (l'utilisateur a créé la tâche) | dismissed
    (refus définitif — jamais re-proposé)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"

    ALL = {PROPOSED, ACCEPTED, DISMISSED}


class AnticipationSuggestion(Base):
    __tablename__ = "anticipation_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    # sha256[:16] de la clé de cluster lexicale (tokens significatifs triés)
    # — l'identité stable du pattern, et la clé d'anti-spam.
    pattern_hash: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(
        String(16), default=SuggestionStatus.PROPOSED, index=True,
    )

    # Le message représentatif (le plus récent du cluster) — pré-remplira
    # le prompt de la tâche planifiée côté UI.
    suggested_prompt: Mapped[str] = mapped_column(Text)
    # Cadence déduite, descriptive : "daily@09:00" | "weekly:mon@09:00".
    suggested_cadence: Mapped[str] = mapped_column(String(40))
    # Échantillon des occurrences [{at, content}] (tronqué) — l'« évidence »
    # montrée à l'utilisateur.
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        # Anti-spam : une row par (user, pattern), quel que soit le status.
        Index("ix_anticipation_user_pattern", "user_id", "pattern_hash",
              unique=True),
    )
