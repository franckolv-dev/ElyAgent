# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/execution_outcome.py
# @brief      Boucle d'auto-diagnostic J1 — verdict d'aboutissement réel
#             d'une exécution automatique (tâche planifiée / mission).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.5.0
# =============================================================================
"""Execution outcome signal — boucle d'auto-diagnostic, jalon J1.

Le « chaînon manquant » de la design note
`docs/external-references/self-diagnostic-improvement-loop-2026-06-13.md` :
les 4 signaux existants (HitlRefusal, HallucinationBlock, ErrorLog,
ProviderSwitch) capturent des *fragments* d'échec, mais rien ne répond à
« la demande a-t-elle RÉELLEMENT abouti ? ». Cette table pose un verdict
par exécution terminée, à côté du statut *déclaré* (`last_status` /
`Mission.status`).

Trois verdicts (`outcome`) :
  - ``succeeded`` : déclaré réussi ET aucun signal faible levé.
  - ``dubious``   : déclaré réussi MAIS au moins un signal faible levé
                    (succès de façade probable — alimenté à J2).
  - ``failed``    : déclaré en erreur / failed / aborted.

J1 enregistre le verdict à partir du statut déclaré (``signals`` vide) ;
J2 remplit ``signals`` avec les heuristiques (réussi sans effet observable,
fallback déclenché, faux « pas d'outil »…) qui font basculer
``succeeded`` → ``dubious``.

Rétention : opérationnel, 90 jours roulants (assez pour détecter une
régression d'infra comme un changement de modèle, cf. design note §6).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionOutcome(Base):
    """Un verdict d'aboutissement par exécution automatique terminée."""

    __tablename__ = "execution_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    # Origine de l'exécution : "scheduled" | "mission" | "chat"
    source: Mapped[str] = mapped_column(String(16), index=True)
    # Référence interne (scheduled_task.id | mission.id | conversation.id)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mission_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Canal de livraison (tâches planifiées) : web | telegram | email | …
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Tier LLM ("A" | "B" | "C" | "IMG" | "MAINTENANCE") — best-effort.
    tier_llm: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    # Modèle effectivement utilisé (dernière étape pour une mission) — best-effort.
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Ce que le SYSTÈME a déclaré : success/error (tâche) ou
    # completed/failed/aborted (mission).
    declared_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Le VERDICT réel : "succeeded" | "dubious" | "failed".
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    # Liste JSON des codes de signaux faibles levés (J2). NULL = aucun.
    signals: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raison courte, lisible (ex : message d'erreur tronqué).
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_execution_outcomes_user_created", "user_id", "created_at"),
        Index("ix_execution_outcomes_source_outcome", "source", "outcome"),
    )
