# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_budget.py
# @brief      Missions autonomes J3 — disjoncteurs D4 : compteurs journaliers,
#             seuils de notification, pause propre + snapshot.
# @license    Elastic License 2.0
# =============================================================================
"""Disjoncteurs des missions autonomes (cadrage D4, arbitrage Franck 11/07).

Pas de plafond bloquant : des seuils de NOTIFICATION (500 actions / 100
appels LLM par jour, surchargeables par mandat). Au franchissement (≥),
`dispatch_tool` sollicite le HITL (« continuer ? ») ; « allow » acquitte le
seuil pour la journée, deny/timeout (30 min) déclenche la pause propre :
statut ``paused`` + ``autonomy_state='paused_budget'`` + snapshot JSON —
la reprise (POST /start) repart exactement là où la mission s'est arrêtée,
compteurs du jour INTACTS.

Compteurs PERSISTÉS (``mission_daily_counters``) : un restart backend ne
réinitialise pas le jour. Tout est best-effort : un incident de comptage ne
doit JAMAIS tuer une mission (fail-open sur le comptage, fail-safe sur la
pause).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.database import async_session
from app.models.mission import MissionDailyCounter

if TYPE_CHECKING:
    from app.services.mission_spec import MissionMandate

logger = logging.getLogger(__name__)


def today_key() -> str:
    """Jour UTC courant, clé de la ligne compteur (YYYY-MM-DD)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _get_or_create(db, mission_id: str) -> MissionDailyCounter:
    day = today_key()
    row = await db.get(MissionDailyCounter, (mission_id, day))
    if row is None:
        row = MissionDailyCounter(
            mission_id=mission_id, day=day,
            tool_actions=0, llm_calls=0, tool_ack=False, llm_ack=False,
        )
        db.add(row)
    return row


async def incr_tool_action(mission_id: str) -> MissionDailyCounter:
    """Incrémente le compteur d'actions d'outils du jour et le renvoie."""
    async with async_session() as db:
        row = await _get_or_create(db, mission_id)
        row.tool_actions = (row.tool_actions or 0) + 1
        await db.commit()
        await db.refresh(row)
        db.expunge(row)
        return row


async def incr_llm_call(mission_id: str) -> None:
    """Incrémente le compteur d'appels LLM du jour. Best-effort : ne lève
    JAMAIS (appelé fire-and-forget après chaque ainvoke mission)."""
    try:
        async with async_session() as db:
            row = await _get_or_create(db, mission_id)
            row.llm_calls = (row.llm_calls or 0) + 1
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — le comptage ne casse pas une mission
        logger.debug("incr_llm_call(%s) ignoré : %s", mission_id, exc)


async def get_today(mission_id: str) -> Optional[MissionDailyCounter]:
    """La ligne compteur du jour, ou None si la mission n'a rien compté."""
    async with async_session() as db:
        row = await db.get(MissionDailyCounter, (mission_id, today_key()))
        if row is not None:
            db.expunge(row)
        return row


async def ack_threshold(mission_id: str, which: str) -> None:
    """Acquitte un seuil (« continuer ») pour la journée : plus de re-prompt
    ce jour-là pour ce compteur. ``which`` ∈ {"tool", "llm"}."""
    if which not in {"tool", "llm"}:
        raise ValueError(f"seuil inconnu : {which!r} — 'tool' ou 'llm'")
    async with async_session() as db:
        row = await _get_or_create(db, mission_id)
        if which == "tool":
            row.tool_ack = True
        else:
            row.llm_ack = True
        await db.commit()


def breached(counter: MissionDailyCounter, mandate: "MissionMandate") -> Optional[str]:
    """Quel seuil NON-acquitté est atteint (≥) ? ``'tool'`` prime sur
    ``'llm'`` ; ``None`` si tout va bien."""
    if not counter.tool_ack and counter.tool_actions >= mandate.budgets.daily_tool_actions_notify:
        return "tool"
    if not counter.llm_ack and counter.llm_calls >= mandate.budgets.daily_llm_calls_notify:
        return "llm"
    return None


async def pause_autonomous_mission(
    mission_id: str,
    reason: str,
    counter: MissionDailyCounter,
    mandate: "MissionMandate",
) -> str:
    """Pause propre D4 : statut ``paused`` + ``autonomy_state='paused_budget'``
    + snapshot ``autonomy_pause_json`` + notification. Chaque étape est
    best-effort — l'état de pause prime sur le confort. Renvoie le message
    (FR) à retourner comme tool-result au LLM de la mission."""
    from app.services import mission_service

    # 1. Statut mission → paused (tolère un statut non pausable, ex. draft :
    #    la mission n'était pas en cours d'exécution, l'état d'autonomie suffit).
    try:
        await mission_service.pause_mission(mission_id)
    except ValueError as exc:
        logger.info("Pause disjoncteur %s : statut non pausable (%s)", mission_id, exc)

    # 2. État d'autonomie → paused_budget (le gate J2 redevient inerte).
    await mission_service.set_autonomy_state(mission_id, "paused_budget")

    # 3. Snapshot : de quoi reprendre en connaissance de cause (J4 le rendra
    #    lisible dans le CARNET).
    snapshot = {
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "counters": {
            "day": counter.day,
            "tool_actions": counter.tool_actions,
            "llm_calls": counter.llm_calls,
        },
        "thresholds": {
            "daily_tool_actions_notify": mandate.budgets.daily_tool_actions_notify,
            "daily_llm_calls_notify": mandate.budgets.daily_llm_calls_notify,
        },
    }
    try:
        from app.models.mission import Mission
        async with async_session() as db:
            m = await db.get(Mission, mission_id)
            if m is not None:
                m.autonomy_pause_json = json.dumps(snapshot, ensure_ascii=False)
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Snapshot de pause %s non écrit : %s", mission_id, exc)

    # 4. Notification (web + telegram + ntfy) — réutilise le canal heartbeat.
    try:
        m = await mission_service.get_mission(mission_id)
        if m is not None:
            from app.services.mission_heartbeat import _notify_terminal
            await _notify_terminal(
                m, "paused",
                f"Disjoncteur : {counter.tool_actions} actions et "
                f"{counter.llm_calls} appels LLM aujourd'hui (seuils "
                f"{mandate.budgets.daily_tool_actions_notify}/"
                f"{mandate.budgets.daily_llm_calls_notify}). Mission mise en "
                f"pause — reprise : bouton Démarrer (l'exécution repartira où "
                f"elle s'est arrêtée).",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notification de pause %s non envoyée : %s", mission_id, exc)

    logger.warning("Mission %s pausée par disjoncteur (%s)", mission_id, reason)
    return (
        "⏸️ Mission mise en pause par le disjoncteur d'autonomie "
        f"({reason}) : seuil journalier atteint sans validation de "
        "l'utilisateur. L'état est sauvegardé — la reprise repartira ici."
    )
