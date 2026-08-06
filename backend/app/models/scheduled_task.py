# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/scheduled_task.py
# @brief      Scheduled tasks — recurring or one-shot prompts executed by the agent.
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
"""Scheduled tasks — recurring or one-shot prompts executed by the agent."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    cron_expression: Mapped[str] = mapped_column(String(100))  # "0 8 * * 1" or "@once 2026-03-25T10:00"
    channel: Mapped[str] = mapped_column(String(50), default="web")  # "web" | "telegram"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    # État de la dernière (ou courante) exécution — feedback UI :
    # "running" | "success" | "error" | None (jamais exécutée). Posé par
    # _execute_task (running au début, success/error à la fin).
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_run_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Cette tâche a-t-elle le DROIT de répondre « [SILENT] » (rien à signaler,
    # ni livraison ni conversation) ? Défaut FAUX — on échoue fermé.
    #
    # Avant le 06/08, la restriction ne vivait que dans le prompt (« pour une
    # tâche qui produit toujours un livrable, NE l'utilise JAMAIS »). Une
    # phrase adressée au modèle n'est pas un verrou : la tâche « Propositions
    # LinkedIn » a rendu [SILENT], sa conversation a été supprimée, et rien
    # n'est parvenu à l'utilisateur ni n'est resté pour l'expliquer.
    # Cf. révision 0033.
    allow_silent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
