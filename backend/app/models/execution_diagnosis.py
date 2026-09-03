# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/execution_diagnosis.py
# @brief      Boucle d'auto-diagnostic J3 — hypothèse de cause + catégorie
#             pour une exécution douteuse / échouée (maillon 2).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Diagnostic d'exécution — boucle d'auto-diagnostic, jalon J3 (maillon 2).

Quand le maillon 1 (J1+J2) pose un verdict ``dubious`` / ``failed``, le
diagnostiqueur (LLM-juge, étend mission_critic) lit les SIGNAUX CORRÉLÉS
(provider_switches, error_log, hitl_refusals, hallucination_blocks de la
fenêtre + les signaux faibles de l'outcome) et formule :

  - une **hypothèse de cause** en langage naturel (raisonnée sur les TRACES,
    jamais sur le code source — qu'il n'a pas) ;
  - une **catégorie** parmi un ensemble fixe (gap_tool / binding / config_tier
    / prompt / code_core / user_interaction / unknown).

L'humain arbitre (J4 : valider / rejeter) — le diagnostiqueur NE valide
jamais ses propres hypothèses (anti-pattern §8). ``status`` porte cet
arbitrage. Une diagnose par outcome max (UNIQUE).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Catégories de cause (design note §4, maillon 2). Frontière A/B/C/D :
#   gap_tool / binding → voie B (créer / re-binder un outil)
#   config_tier / prompt → voie C (patch config/prompt validable)
#   code_core → voie D (ticket humain, jamais d'auto-patch prod)
#   user_interaction → l'exécution attendait l'utilisateur (pas un vrai échec)
DIAGNOSIS_CATEGORIES: frozenset[str] = frozenset({
    "gap_tool",
    "binding",
    "config_tier",
    "prompt",
    "code_core",
    "user_interaction",
    "unknown",
})

DIAGNOSIS_CONFIDENCES: frozenset[str] = frozenset({"low", "medium", "high"})

# Arbitrage humain (J4) ; "merged" = doublon replié sur l'incident canonique
# (dédup des récurrences — posé par la garde, jamais par l'humain).
#
# "obsolete" = la CIBLE de l'incident a disparu (tâche planifiée supprimée).
# Ajouté le 21/08 : ces incidents ne pouvaient plus être tranchés du tout.
# Toute action dessus échouait sur « tâche planifiée introuvable (supprimée ?) »
# et ils restaient « open » indéfiniment, à s'accumuler dans la liste. Les
# rejeter aurait été faux — l'hypothèse n'était pas mauvaise, elle est devenue
# sans objet. Posé par le service, jamais par l'humain (comme "merged").
DIAGNOSIS_STATUSES: frozenset[str] = frozenset({
    "open", "validated", "rejected", "actioned", "merged", "obsolete",
})


class ExecutionDiagnosis(Base):
    """Hypothèse de cause d'une exécution douteuse/échouée — une par outcome."""

    __tablename__ = "execution_diagnoses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_outcome_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("execution_outcomes.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Catégorie de cause (DIAGNOSIS_CATEGORIES).
    category: Mapped[str] = mapped_column(String(24), index=True)
    # Hypothèse en langage naturel (raisonnée sur les traces).
    hypothesis: Mapped[str] = mapped_column(Text)
    # "low" | "medium" | "high"
    confidence: Mapped[str] = mapped_column(String(8), default="medium")
    # Évidence ayant motivé la diagnose (JSON : signaux + compteurs corrélés).
    supporting_signals: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Modèle ayant produit la diagnose (ou "rule-based" en repli sans LLM).
    critic_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Arbitrage humain (J4). "open" tant que non tranché.
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Dédup des récurrences : nombre de runs repliés sur cet incident (le sien
    # + les doublons fusionnés + chaque nouveau run identique) et date du
    # dernier run vu. Reste 1/NULL tant qu'aucun doublon n'a été replié.
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_execution_diagnoses_user_status", "user_id", "status"),
    )
