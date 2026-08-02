# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/replay_guard.py
# @brief      Une reprise de conformité peut refaire un calcul, jamais un acte.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Ne pas rejouer ce qui est déjà parti.

Le 02/08, Franck reçoit son briefing du matin **quatre fois**. Mesuré dans les
journaux :

```
09:00:59   telegram_send_message      ← Ely appelle l'outil
09:02:16   telegram_send_message      ← la vérification a relancé le tour
09:02:37   telegram_send_message      ← et encore
09:04:23   livraison du planificateur ← puis le planificateur livre à son tour
```

Le planificateur n'a tourné **qu'une fois**. Les trois premiers envois viennent
de la boucle de conformité (#288/#289) : elle juge la réponse non conforme,
relance le tour, et le tour **rejoue l'envoi**. Les quatre messages disaient la
même chose — c'est ce qui a mis Franck sur la piste.

👉 **Une reprise peut refaire un CALCUL ; elle ne peut pas défaire un ACTE.**
Ce qui est parti est parti. Le renvoyer ne corrige rien, ça duplique.

Ce que ce module NE fait pas
----------------------------
Il ne retire jamais rien pendant la boucle normale ``agent → outils → agent``.
« Envoie un mail à Paul et un à Marie » est UN tour avec DEUX envois
légitimes ; retirer l'outil au premier appel casserait la demande. Le garde ne
vise que le **rejeu imposé par la vérification**.

⚠️ Le sens de l'erreur est délibéré
------------------------------------
Un envoi qui a ÉCHOUÉ n'est pas « déjà fait » : l'outil reste disponible. Se
tromper dans ce sens renvoie au pire un message qui n'était jamais parti ; se
tromper dans l'autre priverait Franck de son message, sans rattrapage possible
dans le tour.

⚠️ ENGAGEANT n'est pas « sous garde »
--------------------------------------
``telegram_send_message`` est classé **ENGAGEANT** et n'est PAS sous garde
HITL — décision explicite de Franck le 02/08 : « Telegram n'est utilisé que
pour m'envoyer des messages à moi. Je ne vais pas valider à Ely les messages
qu'elle m'envoie. » C'est exactement la séparation posée en #297 : ce qu'un
outil **est** reste distinct de ce qui exige un **accord**. Ce module lit la
nature, pas la garde — sans quoi il ne verrait pas Telegram.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.agent.tool_nature import effect_of

logger = logging.getLogger(__name__)

# Le préfixe qu'écrit la relance de conformité. `conformity` en est la source :
# on l'importe pour qu'un changement de formulation là-bas ne désarme pas le
# garde ici en silence (un pin épingle la coïncidence des deux).
RETRY_MARKER: str = "[Vérification"

# Un outil d'Ely signale son échec en TEXTE, sans lever — le `status` de
# LangChain ne suffit donc pas. Cf. la règle générale : un service peut
# annoncer son échec avec un code de succès (#311).
_ECHEC_PREFIXES: tuple[str, ...] = ("erreur", "error", "échec", "echec")


def _a_echoue(m: ToolMessage) -> bool:
    """Ce retour d'outil dit-il que l'action n'a PAS abouti ?"""
    if str(getattr(m, "status", "") or "").lower() == "error":
        return True
    texte = m.content if isinstance(m.content, str) else str(m.content)
    return texte.lstrip().lower().startswith(_ECHEC_PREFIXES)


def engaging_actions_done(messages: list[BaseMessage]) -> set[str]:
    """Les outils ENGAGEANTS dont un appel a ABOUTI dans ces messages.

    Le nom vit dans le ``AIMessage`` qui a demandé l'appel, le résultat dans le
    ``ToolMessage`` qui suit : on les rapproche par ``tool_call_id``, jamais par
    l'ordre — deux outils lancés en parallèle le casseraient.

    Ne lève jamais : un garde qui plante empêcherait le tour d'aboutir, ce qui
    coûterait plus cher que le défaut qu'il évite.
    """
    demandes: dict[str, str] = {}
    for m in messages:
        if isinstance(m, AIMessage):
            for call in (getattr(m, "tool_calls", None) or []):
                try:
                    demandes[str(call["id"])] = str(call.get("name") or "")
                except Exception as exc:  # noqa: BLE001 — un appel illisible se saute
                    logger.debug("garde de rejeu : appel illisible (%s)", exc)

    faits: set[str] = set()
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        nom = demandes.get(str(getattr(m, "tool_call_id", "")), "")
        if not nom or _a_echoue(m):
            continue
        if effect_of(nom) == "ENGAGEANT":
            faits.add(nom)
    return faits


def after_verification_bounce(messages: list[BaseMessage]) -> bool:
    """La vérification a-t-elle déjà renvoyé ce tour au travail ?"""
    for m in messages:
        contenu = m.content if isinstance(m.content, str) else ""
        if contenu.startswith(RETRY_MARKER):
            return True
    return False


def should_withhold(messages: list[BaseMessage]) -> set[str]:
    """Les outils à NE PAS rebrancher pour la reprise en cours.

    Vide tant que la vérification n'a pas relancé le tour : la boucle normale
    garde tout son outillage.
    """
    if not after_verification_bounce(messages):
        return set()
    return engaging_actions_done(messages)


__all__ = [
    "RETRY_MARKER",
    "after_verification_bounce",
    "engaging_actions_done",
    "should_withhold",
]
