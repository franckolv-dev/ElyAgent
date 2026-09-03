# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/outcome_recording.py
# @brief      Boucle d'auto-diagnostic J2 — orchestration de l'enregistrement
#             d'un verdict execution_outcome enrichi des signaux faibles.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Enregistrement enrichi des verdicts d'aboutissement — jalon J2.

Fait le pont entre les heuristiques PURES (:mod:`facade_detection`) et la
persistance (:func:`signals.record_execution_outcome`) en y ajoutant la
corrélation qui a besoin de la base : un **fallback provider** a-t-il eu
lieu pendant cette exécution ?

Deux entrées, une par site d'exécution automatique :
  - :func:`record_scheduled_outcome` — tâche planifiée (corrélation fallback
    par ``conversation_id``, fiable) ;
  - :func:`record_mission_outcome` — mission (rassemble goal / final_summary /
    outils des steps / modèle ; corrélation fallback best-effort par
    user + fenêtre temporelle).

Tout est best-effort : ne lève jamais (contrat des signaux d'apprentissage).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from app.database import async_session
from app.services.learning.facade_detection import compute_facade_signals
from app.services.learning.signals import record_execution_outcome

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Corrélation fallback (lecture de provider_switches)
# ─────────────────────────────────────────────────────────────────────────


async def fallback_occurred_for_conversation(conversation_id: str | None) -> bool:
    """Un fallback provider a-t-il été enregistré pour cette conversation ?"""
    if not conversation_id:
        return False
    try:
        from app.models.provider_switch import ProviderSwitch
        async with async_session() as db:
            row = (await db.execute(
                select(ProviderSwitch.id)
                .where(ProviderSwitch.conversation_id == conversation_id)
                .limit(1)
            )).first()
        return row is not None
    except Exception as exc:
        logger.debug("fallback_occurred_for_conversation failed (swallowed): %s", exc)
        return False


async def fallback_occurred_for_user_window(
    user_id: str | None, start: datetime | None, end: datetime | None,
) -> bool:
    """Un fallback provider a-t-il eu lieu pour ce user dans la fenêtre
    [start, end] ? Best-effort (les missions ne taguent pas leur
    conversation_id sur les provider_switches)."""
    if not user_id or start is None:
        return False
    try:
        from app.models.provider_switch import ProviderSwitch
        async with async_session() as db:
            q = (
                select(ProviderSwitch.id)
                .where(ProviderSwitch.user_id == user_id)
                .where(ProviderSwitch.created_at >= start)
            )
            if end is not None:
                q = q.where(ProviderSwitch.created_at <= end)
            row = (await db.execute(q.limit(1))).first()
        return row is not None
    except Exception as exc:
        logger.debug("fallback_occurred_for_user_window failed (swallowed): %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────
# Enregistrement par site
# ─────────────────────────────────────────────────────────────────────────


async def record_scheduled_outcome(
    *,
    user_id: str,
    task_id: str,
    conversation_id: str | None,
    channel: str | None,
    declared_status: str,
    goal: str | None,
    final_text: str | None,
    tools_called: list[str] | None,
) -> int | None:
    """Verdict d'une tâche planifiée terminée, signaux faibles inclus."""
    try:
        fb = await fallback_occurred_for_conversation(conversation_id)
        signals = compute_facade_signals(
            goal=goal,
            final_text=final_text,
            tools_called=tools_called,
            fallback_occurred=fb,
        )
        return await record_execution_outcome(
            user_id=user_id,
            source="scheduled",
            source_id=task_id,
            conversation_id=conversation_id,
            channel=channel,
            declared_status=declared_status,
            signals=signals,
        )
    except Exception as exc:
        logger.debug("record_scheduled_outcome failed (swallowed): %s", exc)
        return None


async def record_mission_outcome(
    *,
    mission_id: str,
    user_id: str,
    declared_status: str,
) -> int | None:
    """Verdict d'une mission terminée. Rassemble goal / résumé / outils des
    steps / modèle, corrèle un éventuel fallback, puis persiste."""
    try:
        from app.models.mission import Mission, MissionStep

        goal: str | None = None
        final_text: str | None = None
        model_used: str | None = None
        started: datetime | None = None
        completed: datetime | None = None
        tools_called: list[str] = []

        async with async_session() as db:
            m = (await db.execute(
                select(Mission).where(Mission.id == mission_id)
            )).scalar_one_or_none()
            if m is not None:
                goal = m.goal
                final_text = m.final_summary or m.failure_reason
                started = m.started_at or m.created_at
                completed = m.completed_at
            step_rows = (await db.execute(
                select(
                    MissionStep.tool_name,
                    MissionStep.model_used,
                    MissionStep.created_at,
                )
                .where(MissionStep.mission_id == mission_id)
                .order_by(MissionStep.created_at.desc())
            )).all()

        for tool_name, step_model, _created in step_rows:
            if tool_name:
                tools_called.append(tool_name)
            if model_used is None and step_model:
                model_used = step_model  # dernière étape avec un modèle

        fb = await fallback_occurred_for_user_window(user_id, started, completed)
        signals = compute_facade_signals(
            goal=goal,
            final_text=final_text,
            tools_called=tools_called,
            fallback_occurred=fb,
        )
        return await record_execution_outcome(
            user_id=user_id,
            source="mission",
            source_id=mission_id,
            mission_id=mission_id,
            declared_status=declared_status,
            model_used=model_used,
            signals=signals,
        )
    except Exception as exc:
        logger.debug("record_mission_outcome failed (swallowed): %s", exc)
        return None
