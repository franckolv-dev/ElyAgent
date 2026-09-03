# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/reasoning_replay.py
# @brief      Un raisonnement chiffré que le fournisseur ne sait plus lire
#             se retire du fil ; il ne fait pas basculer la conversation.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Le 03/09/2026 à 06:16, en production :

    400 — The encrypted content for item rs_09cf… could not be verified.
    [fallback] switched 'gpt-5.6-sol' → 'minimax/minimax-m3:free'

Le tier codex rejoue le raisonnement chiffré de chaque tour
(``_make_openai_codex`` : ``store=False`` + ``include=["reasoning.encrypted_content"]``).
Quand le serveur refuse UN de ces items, le gestionnaire de repli lisait un
400 comme une panne du fournisseur et basculait TOUTE la conversation sur le
maillon suivant — ce jour-là un modèle gratuit, pour les vingt tours
suivants.

L'erreur ne dit pas que le fournisseur est en panne : elle dit qu'un bloc du
FIL n'est plus lisible. On retire ces blocs et on rappelle le MÊME modèle ;
le repli ne s'applique que si ce second appel échoue aussi. Le texte, les
appels d'outils et tout le reste du fil restent intacts — seul le
raisonnement, que le modèle peut refaire, s'efface.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_CODE = "invalid_encrypted_content"


def est_un_raisonnement_illisible(exc: BaseException) -> bool:
    """Le serveur refuse-t-il un item de raisonnement chiffré du fil ?"""
    if _CODE in str(exc):
        return True
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if str(err.get("code") or "") == _CODE:
            return True
    return False


def _sans_raisonnement(m: AIMessage) -> AIMessage:
    contenu = m.content
    kwargs = dict(m.additional_kwargs or {})
    change = False
    if isinstance(contenu, list):
        garde = [
            b for b in contenu
            if not (isinstance(b, dict) and b.get("type") == "reasoning")
        ]
        if len(garde) != len(contenu):
            contenu = garde
            change = True
    if "reasoning" in kwargs:
        kwargs.pop("reasoning")
        change = True
    if not change:
        return m
    return m.model_copy(update={"content": contenu, "additional_kwargs": kwargs})


def sans_raisonnement_chiffre(messages: list[Any]) -> list[Any]:
    """Copie du fil sans les blocs de raisonnement des messages du modèle.

    Les messages non touchés sont rendus tels quels (même objet) : un appelant
    peut donc savoir si quelque chose a été retiré en comparant par identité.
    """
    return [
        _sans_raisonnement(m) if isinstance(m, AIMessage) else m
        for m in messages
    ]


async def ainvoke_en_tolerant_le_raisonnement(
    invoke: Callable[[list[Any]], Awaitable[Any]],
    messages: list[Any],
) -> Any:
    """Appelle ``invoke(messages)`` ; si le serveur refuse un raisonnement
    chiffré du fil, rappelle UNE fois sans ces blocs. Toute autre erreur, et
    l'échec du second appel, remontent telles quelles vers le repli."""
    try:
        return await invoke(messages)
    except Exception as exc:  # noqa: BLE001 — on ne retient QUE l'erreur ciblée
        if not est_un_raisonnement_illisible(exc):
            raise
        allege = sans_raisonnement_chiffre(messages)
        if all(a is b for a, b in zip(allege, messages)):
            raise
        logger.warning(
            "[raisonnement] le fournisseur ne lit plus un raisonnement chiffré "
            "du fil — rappel du même modèle sans les blocs de raisonnement",
        )
        return await invoke(allege)
