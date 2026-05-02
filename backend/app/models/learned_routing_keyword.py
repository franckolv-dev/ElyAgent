# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/learned_routing_keyword.py
# @brief      Routing keywords learned at runtime — self-improvement of the
#             quick keyword router based on user reformulations.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Learned routing keywords.

Le router de supervisor.py utilise des regex hardcodées pour mapper rapidement
une query vers un specialist (workspace, research, infra…). Mais le langage
évolue : abréviations FR (« RDV », « actus »), néologismes, vocabulaire
métier propre à un user. Cette table stocke des keywords additionnels
proposés/validés à partir de l'analyse des reformulations user.

Workflow d'apprentissage (handled by `services/routing_learning.py`) :
  1. Un job MAINTENANCE quotidien scanne les conversations récentes.
  2. Il détecte les paires « query A → query B reformulant A » (heuristique
     temporelle + similarité sémantique).
  3. Pour chaque paire, il demande au LLM MAINTENANCE : « Le router a envoyé
     A sur domaine X. La reformulation B route sur Y. Quels mots de A
     auraient dû matcher Y ? »
  4. Les keywords proposés sont insérés ici avec ``source='auto-proposed'``.
  5. Après N matchs confirmés (incrément de ``confidence``), passent à
     ``source='auto-confirmed'`` et ``active=True`` → utilisés au routing.

Un admin peut aussi pousser des keywords manuellement via l'API admin
(``source='manual'`` → directement actifs).

Sécurité : les keywords sont **per-user** par défaut (``user_id`` rempli) pour
éviter qu'un user pollue le routing global. Un keyword promu globalement
(``user_id=None``) requiert un acte explicite de l'admin.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LearnedRoutingKeyword(Base):
    __tablename__ = "learned_routing_keywords"
    __table_args__ = (
        # Pas deux fois le même mot pour le même user/domain (évite les doublons
        # de propositions auto). NULL user_id = keyword global, peut coexister
        # avec un per-user.
        UniqueConstraint("user_id", "keyword", "domain", name="uq_learned_kw_user_term_domain"),
        Index("ix_learned_kw_active_domain", "active", "domain"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # user_id NULL = keyword global (admin promotion required)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # The token / phrase to match (case-insensitive, word-boundary applied at runtime).
    # Can be a single word (« actus »), a multi-word phrase (« mes rappels du jour »),
    # or a regex fragment if source='manual' and the admin knows what they're doing.
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    # Target specialist : workspace, research, infra, creative, data, memory, desktop, general
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    # 'manual'        : pushed by admin, directly active=True
    # 'auto-proposed' : suggested by the maintenance LLM, active=False until confirmed N times
    # 'auto-confirmed': passed the confirmation threshold, active=True
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # How many times this keyword was suggested or matched a real reformulation.
    # auto-proposed needs >= AUTO_CONFIRM_THRESHOLD to flip active=True.
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Whether the keyword is used by the live router. Always True for 'manual',
    # toggled by the maintenance job for auto-* entries.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # When this keyword last contributed to a successful (non-reformulated) routing.
    # NULL until the first match. Used to prune stale entries.
    last_matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Audit trail.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Optional explanation surfaced in the admin review UI (e.g. extracted
    # by the maintenance LLM : « detected when user reformulated 'mes RDV
    # du jour' after 'mon agenda' was misrouted »).
    rationale: Mapped[str | None] = mapped_column(String(500), nullable=True)
