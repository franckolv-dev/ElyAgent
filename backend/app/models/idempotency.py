# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/idempotency.py
# @brief      IdempotencyRecord — « jamais deux fois par accident » (P1/J3).
# @license    Elastic License 2.0
# =============================================================================
"""Enregistrement d'idempotence : une action déjà exécutée (par sa clé) n'est
pas ré-exécutée tant que l'enregistrement n'a pas expiré.

La clé est l'empreinte du plan d'action (J2) — elle identifie l'action ET son
auteur. Le résultat mémorisé est borné et traité comme transitoire/sensible
(même statut que l'historique de conversation).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    # Clé = empreinte du plan d'action (sha256). Unique par (action, user).
    key:           Mapped[str]        = mapped_column(String, primary_key=True)
    user_id:       Mapped[str | None] = mapped_column(String, nullable=True)
    capability_id: Mapped[str]        = mapped_column(String, nullable=False)
    # Résultat mémorisé (borné) renvoyé en cas de doublon dans la fenêtre TTL.
    result:        Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=_now)
    expires_at:    Mapped[datetime]   = mapped_column(DateTime(timezone=True), nullable=False)
