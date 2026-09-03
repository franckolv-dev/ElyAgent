# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/pii.py
# @brief      Cycle PII des missions — le dernier trou documenté de la
#             frontière souveraineté (chantier 2026-06-12).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""Cycle anonymise/dé-anonymise du chemin missions.

INVARIANT (le même que le chat) : **la base et l'utilisateur vivent dans le
monde réel ; seul le LLM vit dans le monde des placeholders.**

- Les prompts composés (goal + sorties d'outils + plan) sont anonymisés
  JUSTE AVANT chaque ``ainvoke`` de mission (plan / act / eval / replan /
  critic) — couche 1 regex toujours, couche 2 NER selon le flag global,
  en mode contenu-machine (``ner_detection=False`` : pas de détection
  fraîche, la PII déjà au vault reste masquée).
- TOUT ce que le LLM produit est dé-anonymisé À LA SORTIE, avant d'être
  parsé / persisté / montré : ``raw`` des nodes (plans, évaluations,
  résumés), args des tool_calls (dans ``dispatch_tool``), questions
  ask_user, notifications du heartbeat.

Conséquence clé de l'invariant : AUCUN placeholder ne touche jamais le
disque ni un canal utilisateur → le vault n'a pas besoin de survivre aux
redémarrages ni au TTL du registre. Une perte de vault entre deux ticks
d'une mission longue est sans danger : le tick suivant ré-anonymise à
frais nouveaux, et chaque prompt est auto-cohérent. C'est ce qui rend ce
design radicalement plus simple qu'une table de vault persistante.

Identité de filtre : ``mission:<mission_id>`` dans le registre partagé
``conversation_filters`` (LRU + TTL 24 h, mêmes garanties B-7 que le chat).
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage

from app.services.security_filter import SecurityFilter

logger = logging.getLogger(__name__)


def mission_filter(mission_id: str) -> SecurityFilter:
    """Filtre PII de la mission — même instance pour toute la durée de vie
    en mémoire (registre partagé, clé préfixée pour ne jamais collisionner
    avec un conversation_id)."""
    from app.services.conversation_filters import get_filter
    return get_filter(f"mission:{mission_id}")


def anonymize_messages(sf: SecurityFilter, messages: list[BaseMessage]) -> list[BaseMessage]:
    """Anonymise le contenu de chaque message AVANT l'envoi au LLM.

    Retourne de NOUVELLES instances (jamais de mutation : les objets
    d'origine peuvent être réutilisés par le fallback ou les logs côté
    monde réel). Mode contenu-machine : les prompts de mission sont des
    compositions goal + sorties d'outils — la couche 1 regex y fait le
    travail (emails / téléphones / IBAN / CB), pas de détection NER fraîche.
    """
    out: list[BaseMessage] = []
    for m in messages:
        content = m.content
        if isinstance(content, str) and content:
            anonymized = sf.anonymize(content, ner_detection=False)
            if anonymized != content:
                m = m.model_copy(update={"content": anonymized})
        out.append(m)
    return out


def deanonymize_any(sf: SecurityFilter, value: Any) -> Any:
    """Dé-anonymise récursivement str / dict / list — miroir de
    ``tool_node._deanonymize_value`` pour le chemin missions. Tout artefact
    SORTANT du LLM passe ici avant d'être parsé, persisté ou affiché."""
    if isinstance(value, str):
        return sf.deanonymize(value)
    if isinstance(value, dict):
        return {k: deanonymize_any(sf, v) for k, v in value.items()}
    if isinstance(value, list):
        return [deanonymize_any(sf, v) for v in value]
    return value
