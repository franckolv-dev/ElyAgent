# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/proposed_patch.py
# @brief      Boucle d'auto-diagnostic J5 — correctif config/prompt PROPOSÉ
#             par Ely, validable + applicable + réversible (voie C).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""Correctif proposé — boucle d'auto-diagnostic, jalon J5 (voie C).

Quand un incident (J3/J4) pointe une cause de catégorie *prompt*, Ely peut
PROPOSER un correctif concret. La proposition n'est JAMAIS auto-appliquée :
l'humain voit le **diff**, puis **applique** (réversible — l'ancienne valeur
est conservée) ou **rejette** (anti-pattern §8 : garder l'humain dans la
boucle, jamais d'auto-patch).

Périmètre v1 (décidé 14/06) : ``kind="prompt"`` sur ``target_type="scheduled_task"``
(``field="prompt"``) — réversible, scopé à la tâche du user, zéro impact sur
l'infra partagée. Le tier/config global (l'autre exemple du 13/06) est
volontairement HORS périmètre v1 (config admin héritée par tous → design
d'application plus prudent à part).

Cycle de vie : ``proposed`` → ``applied`` → (``reverted``) | ``rejected``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


PATCH_KINDS: frozenset[str] = frozenset({"prompt"})  # v1 ; "config" plus tard
PATCH_TARGET_TYPES: frozenset[str] = frozenset({"scheduled_task"})  # v1
PATCH_STATUSES: frozenset[str] = frozenset({
    "proposed", "applied", "rejected", "reverted",
})


class ProposedPatch(Base):
    """Un correctif proposé par Ely pour une cible config/prompt."""

    __tablename__ = "proposed_patches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_diagnosis_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("execution_diagnoses.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    kind: Mapped[str] = mapped_column(String(16), default="prompt")
    target_type: Mapped[str] = mapped_column(String(24), default="scheduled_task")
    target_id: Mapped[str] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(32), default="prompt")

    # Valeur AVANT (snapshot pris à l'application, pour un revert exact) / APRÈS.
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    critic_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
