# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/auto_tool_generation.py
# @brief      C4-2 — le déclencheur : capacité manquante consignée →
#             génération AUTOMATIQUE d'un outil candidate + notification.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Le vrai « auto » de bout en bout (backlog #57, câblé en C4-2).

Depuis juin, la chaîne existait SANS déclencheur : gap consigné → bouton
admin « Générer un outil » → candidate → validation → binding. Ce module la
déclenche tout seul quand `find_tool` consigne une capacité réellement
absente — la vision validée : *« elle crée, me le soumet, je valide, elle
peut l'utiliser »*.

Garde-fous (dans l'ordre) :
  1. Flag ``auto_tool_generation_enabled`` (ON par défaut, kill-switch).
  2. Une tentative max PAR GAP et PAR BOOT (``_attempted_cases`` in-process) —
     un gap re-consigné (dédup) ne re-brûle pas du tier-S en boucle.
  3. Pré-check sémantique anti-doublon : si le catalogue contient déjà un
     outil correspondant (trou de binding, leçon Drive/Sheets), on ne génère
     PAS — find_tool amont l'aurait trouvé, mais ce chemin sert aussi
     l'endpoint admin qui n'a pas cette garde.
  4. La sortie est TOUJOURS ``candidate`` (jamais auto-promue) : la
     validation humaine reste le verrou avant tout binding (arbitrage 19/07).

Best-effort intégral : aucune exception ne remonte au tour utilisateur.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Une tentative par gap et par boot — reset au restart (volontaire : un
# redémarrage offre une seconde chance aux générations échouées).
_attempted_cases: set[int] = set()


def reset_attempts() -> None:
    """Tests uniquement — repart d'un état vierge."""
    _attempted_cases.clear()


async def maybe_generate_for_gap(
    case_id: int, capability: str, user_id: str,
) -> dict | None:
    """Génère un outil candidate pour un gap consigné. Jamais levant.

    Retourne le résumé de génération (dict) quand une génération a eu lieu,
    ``None`` quand une garde a court-circuité (flag OFF, déjà tenté,
    outil existant, entrées invalides).
    """
    try:
        from app.config import get_settings

        if not get_settings().auto_tool_generation_enabled:
            return None
        if not case_id or not capability or not user_id:
            return None
        if case_id in _attempted_cases:
            logger.debug("auto_tool_gen: gap #%s déjà tenté ce boot — skip", case_id)
            return None
        _attempted_cases.add(case_id)

        # 3. Pré-check sémantique : existe-t-il DÉJÀ un outil pour ça ?
        from app.skills.builtin.find_tool_skill import capability_has_existing_tool

        existing = await capability_has_existing_tool(capability)
        if existing:
            logger.info(
                "auto_tool_gen: gap #%s « %.60s » couvert par l'outil existant "
                "%r — pas de génération (trou de binding, pas de capacité absente)",
                case_id, capability, existing,
            )
            return None

        logger.info(
            "auto_tool_gen: génération candidate pour gap #%s « %.80s »",
            case_id, capability,
        )
        from app.services.learning.tool_creator import generate_and_persist_tool

        summary = await generate_and_persist_tool(
            task_description=capability,
            user_id=user_id,
            from_failure_case_ids=[case_id],
        )
        if summary.get("status") == "created":
            from app.services.learning.candidate_notify import notify_candidate

            await notify_candidate(summary.get("tool_name", "?"), capability)
            # NB : notify est best-effort et avale ses erreurs — ne pas
            # affirmer « envoyée » ici (le succès réel est loggé par _push).
            logger.info(
                "auto_tool_gen: candidate %r créée pour gap #%s (notification demandée)",
                summary.get("tool_name"), case_id,
            )
        else:
            # Pas de notification d'échec (bruit) — le gap reste ouvert dans
            # « Capacités manquantes », l'admin garde le bouton manuel.
            logger.info(
                "auto_tool_gen: génération non aboutie pour gap #%s (status=%s)",
                case_id, summary.get("status"),
            )
        return summary
    except Exception as exc:  # noqa: BLE001 — ne casse jamais le tour
        logger.warning("auto_tool_gen: échec silencieux pour gap #%s: %s", case_id, exc)
        return None
