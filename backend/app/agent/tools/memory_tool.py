# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Memory tools — save user preferences and constraints in real time.

These tools allow the agent to immediately persist user preferences (tone,
format, style) and behavioral constraints when the user explicitly expresses
them during a conversation. Without these tools, preferences were only
extracted post-session and could be lost or delayed.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.memory_manager import get_memory_manager


@tool
async def save_user_preference(
    preference: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Sauvegarde immédiatement une préférence de communication de l'utilisateur
    en mémoire permanente.

    Utilise cet outil DÈS QUE l'utilisateur exprime explicitement une préférence
    sur la façon dont il veut être servi : ton, format, style, longueur des réponses,
    langue, émojis, markdown, niveau de détail, humour, etc.

    Exemples de déclencheurs :
    - "arrête les émojis" → preference="Ne jamais utiliser d'émojis dans les réponses"
    - "sois plus concise" → preference="Réponses courtes et directes, sans détails superflus"
    - "ne mets plus de markdown" → preference="Ne pas utiliser de formatage markdown"
    - "réponds toujours en anglais" → preference="Répondre en anglais"
    - "tu peux me tutoyer" → preference="Tutoyer l'utilisateur"

    La préférence est stockée de façon permanente et sera appliquée à toutes les
    conversations futures.

    Args:
        preference: Description claire et directement actionnable de la préférence
                    (ex: "Ne jamais utiliser d'émojis dans les réponses")
    """
    memory = get_memory_manager()
    await memory.store_preference(preference, user_id)
    return f"Préférence enregistrée : {preference}"


@tool
async def save_constraint(
    rule: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Sauvegarde une règle ou contrainte permanente apprise d'un refus ou d'une
    limite explicitement posée par l'utilisateur.

    Utilise cet outil quand l'utilisateur pose une règle ferme sur ce qu'Éli
    ne doit JAMAIS faire (limite de sécurité, comportement interdit, règle absolue).

    Exemples de déclencheurs :
    - "ne contacte jamais cette adresse email" → rule="Ne jamais envoyer d'email à X"
    - "ne supprime jamais mes fichiers sans confirmation explicite" → rule correspondante
    - "ne partage pas mes données avec des services tiers"

    Args:
        rule: Règle claire et permanente à respecter absolument
    """
    memory = get_memory_manager()
    await memory.store_constraint(rule, user_id)
    return f"Contrainte enregistrée : {rule}"
