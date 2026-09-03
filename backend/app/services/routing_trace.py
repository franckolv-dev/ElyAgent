# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/routing_trace.py
# @brief      RoutingDecision traçable (C3d-4) — chaque décision de routage
#             LLM émet un EventEnvelope kind=routing + une ligne compacte.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""Trace structurée des décisions de routage LLM.

Pourquoi (diagnostics 18-19/07/2026) : les décisions étaient éparpillées en
logs texte hétérogènes ([chantier4], TIMING[router-*], [fallback] switched…)
— il a fallu déduire le TIER d'un sous-agent du NOM du modèle dans une ligne
TIMING pour comprendre pourquoi les switchs de routage de l'admin restaient
sans effet (#210). Ce module donne UNE forme unique, requêtable via les
EventEnvelope (kind=routing) et greppable via la ligne « [routing] ».

Vocabulaire des aspects (capability_id de l'événement) :
  - ``slm``               : choix SLM-vs-cloud du IntentRouter (nodes)
  - ``turn``              : tier classé + chaîne/position au départ du tour
  - ``domain``            : spécialiste retenu par le routeur (dispatch)
  - ``subagent``          : modèle/tier résolus par CYCLE de sous-agent
  - ``subagent_fallback`` : rotation locale d'un sous-agent (raison classée)
  - ``switch``            : bascule de chaîne chantier4 (from → to → reason),
                            outcome ``exhausted`` quand la chaîne est épuisée

Contrat : ``note()`` ne lève JAMAIS (le routage ne doit pas casser un tour)
et ne stocke rien lui-même — l'EventEnvelope porte tout (ring diagnostic +
log JSON + OTel), attributs assainis par la sanitisation P1.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Vocabulaire fermé — un aspect inconnu passe quand même (forward-compat)
# mais est signalé en debug pour attraper les fautes de frappe.
KNOWN_ASPECTS = frozenset({
    "slm", "turn", "domain", "subagent", "subagent_fallback", "switch",
})


def note(
    conversation_id: str,
    aspect: str,
    *,
    user_id: str = "",
    decision: str = "",
    **attrs: object,
) -> None:
    """Émet une décision de routage. Jamais bloquant, jamais levant.

    ``decision`` est la valeur principale (tier retenu, provider activé,
    domaine choisi…) — reprise dans ``outcome`` de l'événement pour les
    requêtes ; le reste des ``attrs`` part dans ``attributes`` (assainis).
    """
    try:
        if aspect not in KNOWN_ASPECTS:
            logger.debug("routing_trace: aspect inconnu %r (toléré)", aspect)
        from app.services.event_envelope import EventKind, emit

        conv8 = (conversation_id or "")[:8]
        emit(
            EventKind.ROUTING,
            user_id=user_id,
            capability_id=aspect,
            outcome=str(decision) if decision else None,
            attributes={"conv": conv8, **attrs},
        )
        logger.info(
            "[routing] conv=%s %s=%s %s",
            conv8, aspect, decision,
            " ".join(f"{k}={v}" for k, v in attrs.items()),
        )
    except Exception as exc:  # noqa: BLE001 — la trace ne casse jamais un tour
        logger.debug("routing_trace.note skipped: %s", exc)
