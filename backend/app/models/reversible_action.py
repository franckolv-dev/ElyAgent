# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/reversible_action.py
# @brief      ReversibleActionRecord — « Ely peut annuler ce qu'elle a fait ».
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Entrée du Reversible Action Journal (substrat, suite de P1).

Une action mutante dont le ``CapabilityManifest`` déclare une ``compensation``
est journalisée APRÈS son succès, avec le minimum nécessaire pour l'annuler
(``compensation_args`` = identifiants seulement — jamais de secret ni de corps
de message). ``undo`` exécute la compensation enregistrée et passe l'entrée en
``reverted``.

``compensation_args`` est traité comme transitoire/sensible (même statut que le
``result`` d'idempotence) : borné, jamais loggé, purgé à expiration.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReversibleActionRecord(Base):
    __tablename__ = "reversible_actions"

    # uuid de l'entrée (≠ empreinte : une même action peut être rejouée).
    id:                Mapped[str]            = mapped_column(String, primary_key=True)
    user_id:           Mapped[str]            = mapped_column(String, index=True, nullable=False)
    capability_id:     Mapped[str]            = mapped_column(String, nullable=False)
    # Empreinte du plan d'action (J2) — corrèle avec idempotence + événements.
    fingerprint:       Mapped[str | None]     = mapped_column(String, nullable=True)
    # Référence de compensation (ex. "restore_from_trash"), résolue au runtime.
    compensation:      Mapped[str]            = mapped_column(String, nullable=False)
    # JSON minimal des identifiants nécessaires à l'annulation (borné).
    compensation_args: Mapped[str]            = mapped_column(Text, nullable=False)
    # recorded | reverted | revert_failed | expired
    status:            Mapped[str]            = mapped_column(String, default="recorded", nullable=False)
    created_at:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)
    # Fenêtre d'annulation : au-delà → `expired`, annulation refusée.
    expires_at:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), nullable=False)
    reverted_at:       Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
