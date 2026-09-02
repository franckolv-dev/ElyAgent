# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/hitl_request.py
# @brief      HITL — demandes de validation humaine, persistées pour survivre
#             au redémarrage du backend.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Demandes de validation humaine (HITL), persistées.

Avant V0-2, tout l'état HITL vivait dans un dict en mémoire : un redémarrage
pendant une mission de nuit perdait les demandes en attente, et la décision
prise ensuite depuis le téléphone tombait dans le vide (``resolve()`` rendait
``False``, le routeur un 404).

Cette table est la trace durable de la demande **et** de son issue. Elle ne
ressuscite pas la coroutine qui attendait — c'est de la reprise d'exécution,
pas de la persistance — mais elle garantit qu'aucune décision humaine n'est
plus perdue, et elle rend l'historique des validations enfin auditable.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HitlRequest(Base):
    __tablename__ = "hitl_requests"

    # L'action_id court (uuid4[:8]) déjà utilisé par les boutons Telegram
    # et les tokens signés — c'est lui la clé naturelle.
    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # "pending" | "allow" | "deny" | "ban"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Motif libre. Vaut "timeout" quand personne n'a répondu — un silence
    # n'est PAS un refus délibéré (cf. #150 et record_hitl_refusal).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
