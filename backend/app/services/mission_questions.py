# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_questions.py
# @brief      Une mission libre pose une question à l'utilisateur, attend sa
#             réponse, et reprend avec elle.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le droit de s'arrêter pour demander (07/09/2026).

Mission « RDV » du 06/09 : « si plusieurs créneaux sont libres, demande-moi
lequel ». La consigne disait « tu agis, tu ne demandes pas » et aucun outil
ne permettait de demander : le modèle a planifié « demander le créneau » six
fois, a réservé sans choix, puis a tourné — 217 actions, 3,7 M tokens.

Trois gestes, tous best-effort sur la notification, jamais sur l'état :

- ``poser`` : la mission passe en ``waiting_user`` avec sa question ; la
  question va au carnet ; l'utilisateur est prévenu (web, ntfy, Telegram).
  Le heartbeat ne réveille pas une mission qui attend
  (``list_due_missions`` ne sélectionne que ``running`` / ``planning``).
- ``repondre`` : la réponse va au carnet sous la question, la mission
  repasse ``running`` et redevient due tout de suite. Le passage suivant
  relit question et réponse en tête de sa consigne.
- ``notifier`` : les canaux, isolés les uns des autres — calqué sur
  ``mission_spec_runtime.notify_ask_user`` et ``_notify_terminal``.

Une question n'expire pas : contrairement à une validation HITL (30 min),
une mission peut attendre son utilisateur des heures. Elle ne consomme rien
pendant ce temps.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.mission import Mission

logger = logging.getLogger(__name__)

SECTION_CARNET = "Questions et réponses"
_MAX_QUESTION = 2000
_MAX_REPONSE = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def poser(mission_id: str, question: str) -> Mission:
    """running|planning → waiting_user, question au carnet, utilisateur prévenu.

    Lève ``ValueError`` si la mission n'est pas en cours : une question posée
    par une mission déjà terminée n'a personne pour y répondre.
    """
    from app.services import mission_service
    from app.services.mission_workspace import carnet_append_section

    question = " ".join((question or "").split())[:_MAX_QUESTION]
    if not question:
        raise ValueError("une question vide ne se pose pas")
    m = await mission_service._transition(
        mission_id, from_={"running", "planning"}, to="waiting_user",
        pending_question=question, question_asked_at=_utcnow(),
        next_tick_at=None,
    )
    try:
        carnet_append_section(mission_id, SECTION_CARNET, f"**Q :** {question}")
    except Exception as exc:  # noqa: BLE001 — le carnet est une mémoire, pas un verrou
        logger.warning("mission %s : question non consignée au carnet (%s)", mission_id, exc)
    try:
        await notifier(mission_id, question)
    except Exception as exc:  # noqa: BLE001 — la notification n'est pas l'état
        logger.warning("mission %s : notification de la question échouée (%s)", mission_id, exc)
    logger.info("mission %s : question posée, en attente — %.120s", mission_id, question)
    return m


async def repondre(mission_id: str, reponse: str) -> Mission:
    """waiting_user → running, réponse au carnet, mission due tout de suite.

    Lève ``ValueError`` si la mission n'attend rien : l'appelant (l'API) en
    fait un 409, pas un succès silencieux.
    """
    from app.services import mission_service
    from app.services.mission_workspace import carnet_append_section

    reponse = (reponse or "").strip()[:_MAX_REPONSE]
    if not reponse:
        raise ValueError("une réponse vide ne relance rien")
    m = await mission_service.get_mission(mission_id)
    if m is None or m.status != "waiting_user":
        raise ValueError("cette mission n'attend pas de réponse")
    question = m.pending_question or "(question précédente)"
    try:
        carnet_append_section(
            mission_id, SECTION_CARNET,
            f"**R :** {reponse}  _(à « {question[:200]} »)_",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mission %s : réponse non consignée au carnet (%s)", mission_id, exc)
    m = await mission_service._transition(
        mission_id, from_={"waiting_user"}, to="running",
        pending_question=None, question_asked_at=None, next_tick_at=_utcnow(),
    )
    logger.info("mission %s : réponse reçue — la mission reprend", mission_id)
    return m


def bloc_pour_la_consigne(mission_id: str) -> str:
    """Les questions posées et leurs réponses, pour la tête du passage.

    Le carnet les porte déjà, mais tronqué par la tête à 4 000 caractères :
    une réponse ne doit pas dépendre de sa place dans le carnet.
    """
    from app.services.mission_workspace import extract_section

    try:
        contenu = extract_section(mission_id, SECTION_CARNET)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mission %s : section questions illisible (%s)", mission_id, exc)
        return ""
    if not contenu:
        return ""
    return (
        "\n── QUESTIONS POSÉES À L'UTILISATEUR, ET SES RÉPONSES ──\n"
        f"{contenu[-3000:]}\n"
        "Tiens compte de ses réponses. Ne repose pas une question déjà répondue.\n"
    )


async def notifier(mission_id: str, question: str) -> None:
    """Prévenir l'utilisateur, sur tous les canaux, chacun isolé."""
    async with async_session() as db:
        mission = (await db.execute(
            select(Mission).where(Mission.id == mission_id)
        )).scalar_one_or_none()
    if mission is None:
        return
    try:
        from app.agent.missions.pii import mission_filter
        question = mission_filter(mission_id).deanonymize(question or "")
    except Exception:  # noqa: BLE001 — la notification prime
        pass
    titre = mission.title or mission_id
    texte = (
        f"❓ **Mission « {titre} » — question**\n\n{question}\n\n"
        "_Réponds depuis la page Missions : la mission attend ta réponse._"
    )

    # 1. Web : la conversation « [Missions] Notifications », comme les fins de mission
    try:
        from app.models.conversation import Conversation, Message
        async with async_session() as db:
            conv = (await db.execute(
                select(Conversation)
                .where(Conversation.user_id == mission.user_id)
                .where(Conversation.title.like("[Missions]%"))
                .limit(1)
            )).scalar_one_or_none()
            if conv is None:
                conv = Conversation(user_id=mission.user_id, title="[Missions] Notifications")
                db.add(conv)
                await db.flush()
            db.add(Message(conversation_id=conv.id, role="assistant", content=texte))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mission %s : question non persistée côté web (%s)", mission_id, exc)

    # 2. Web : événement poussé sur toutes les sockets de l'utilisateur
    try:
        from app.services import ws_registry
        await ws_registry.send_text_all(mission.user_id, json.dumps({
            "type": "mission_question",
            "mission_id": mission_id,
            "mission_title": titre,
            "question": question,
        }, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("mission %s : push ws de la question échoué (%s)", mission_id, exc)

    # 3. ntfy
    ntfy_url = os.environ.get("NTFY_URL")
    if ntfy_url:
        try:
            import httpx

            from app.services.ntfy_headers import ascii_header
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    ntfy_url,
                    headers={
                        "Title": ascii_header(f"Mission « {titre} » — question")[:120],
                        "Tags": "question",
                        "Priority": "high",
                    },
                    content=question[:500].encode("utf-8"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mission %s : ntfy question échoué (%s)", mission_id, exc)

    # 4. Telegram, si la mission en vient
    if mission.source == "channel" and (mission.source_ref or "").startswith("telegram:"):
        try:
            tg_chat_id = int(mission.source_ref.split(":", 1)[1])
            from app.channels import telegram_bot as _tb
            if _tb._bot_app is not None:
                # parse_mode=None volontaire : texte contrôlé par l'utilisateur
                await _tb._bot_app.bot.send_message(
                    chat_id=tg_chat_id,
                    text=(f"⏸ Mission « {titre} » — question :\n\n{question}\n\n"
                          "Réponds depuis la page Missions de l'interface web."),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mission %s : Telegram question échoué (%s)", mission_id, exc)


__all__ = ["SECTION_CARNET", "bloc_pour_la_consigne", "notifier", "poser", "repondre"]
