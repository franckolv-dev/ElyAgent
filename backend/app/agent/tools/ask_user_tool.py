# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/ask_user_tool.py
# @brief      `ask_user` — une mission pose une question à l'utilisateur et
#             s'arrête jusqu'à sa réponse.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""L'outil est le VERROU, pas la consigne (07/09/2026).

Une mission n'a personne devant l'écran. Jusqu'ici la consigne lui disait
donc « tu agis, tu ne demandes pas » — et « réserve un créneau ; si
plusieurs sont libres, demande-moi lequel » finissait en 217 actions sans
jamais pouvoir demander. Cet outil donne à la mission le droit de
s'arrêter : la question est enregistrée, l'utilisateur prévenu, le passage
se termine, et la mission reprend avec la réponse dans sa consigne.

Au chat, l'utilisateur est là : l'outil renvoie la question à la réponse
en texte, sans rien changer.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.agent.tool_context import CURRENT_CONVERSATION_ID
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)

_STATUTS_QUI_PEUVENT_DEMANDER = frozenset({"running", "planning"})


@register(
    domain=Domain.UNIVERSAL,
    skill_name="ask_user",
    skill_display_name="Question à l'utilisateur",
    skill_description=(
        "Poser une question à l'utilisateur depuis une mission, et attendre "
        "sa réponse avant de continuer."
    ),
    skill_icon="❓",
)
@tool
async def ask_user(question: str) -> str:
    """Pose UNE question à l'utilisateur et attend sa réponse.

    Dans une MISSION : la mission s'arrête, l'utilisateur est prévenu (web,
    téléphone, Telegram), et la mission reprend avec sa réponse dès qu'il
    l'a donnée. Appelle-le quand tu hésites entre plusieurs choix que
    l'objectif te demande de lui soumettre, quand une action l'engage
    (créer un compte, payer, écrire à un tiers) sans son accord explicite,
    ou quand tu es bloqué et que lui seul peut débloquer. N'invente jamais
    sa réponse. Pose une question précise, avec les options si tu les as.

    Dans une conversation, l'utilisateur est devant l'écran : pose ta
    question directement dans ta réponse.

    Args:
        question: La question, précise et autonome (options comprises).
    """
    conversation_id = CURRENT_CONVERSATION_ID.get() or ""
    mission = None
    if conversation_id:
        try:
            from app.services import mission_service

            mission = await mission_service.get_mission(conversation_id)
        except Exception as exc:  # noqa: BLE001 — pas de mission = conversation
            logger.debug("ask_user : mission %s illisible (%s)", conversation_id, exc)
            mission = None
    if mission is None or (mission.status or "") not in _STATUTS_QUI_PEUVENT_DEMANDER:
        return (
            "Tu es dans une conversation, l'utilisateur est devant l'écran : "
            "pose ta question directement dans ta réponse, en texte."
        )

    from app.services import mission_questions

    try:
        await mission_questions.poser(mission.id, question)
    except ValueError as exc:
        return f"Question non posée : {exc}"
    return (
        "Question posée à l'utilisateur. La mission est EN ATTENTE de sa "
        "réponse : ce passage s'arrête ici, tu reprendras avec sa réponse. "
        "N'appelle plus aucun outil."
    )
