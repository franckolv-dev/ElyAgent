# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/llm_deadline.py
# @brief      Échéance MURALE par appel LLM (C3d-2) — asyncio.wait_for autour
#             de ainvoke, TimeoutError classée TIMEOUT → rotation de chaîne.
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
"""Échéance murale par appel LLM.

Pourquoi (incident 18/07/2026) : les timeouts httpx des clients sont PAR
LECTURE réseau — un stream qui envoie un octet de temps en temps ne les
déclenche jamais. Un appel de synthèse sous-agent a pendu **907 s** sans
erreur ni timeout, silence total côté utilisateur. Aucun site d'appel LLM
(hors delegate_tool et le fast-path SLM) n'avait d'échéance totale.

Contrat : le ``TimeoutError`` levé contient « timed out » — le mot-clé que
``fallback_manager.classify_exception`` mappe sur ``FailoverReason.TIMEOUT``.
Une échéance dépassée déclenche donc la rotation de chaîne existante
(chantier4) exactement comme un timeout réseau réel, sans câblage de plus.
``asyncio.wait_for`` ANNULE l'appel sous-jacent → la requête httpx est coupée
(plus de connexion zombie qui occupe un slot provider).

Valeurs par tier dans Settings (env-overridables) :
``LLM_DEADLINE_{SIMPLE,MEDIUM,COMPLEX,MISSION_ACT,ROUTER}_S``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings


def deadline_for_tier(tier: Any) -> float:
    """Échéance murale (secondes) pour un tier de complexité.

    Accepte l'enum ``ComplexityTier``, sa ``.value`` string, ou ``None`` —
    tout inconnu retombe sur MEDIUM (défaut sûr : borne sans étrangler).
    """
    s = get_settings()
    name = str(getattr(tier, "value", tier) or "").lower()
    return {
        "simple": s.llm_deadline_simple_s,
        "medium": s.llm_deadline_medium_s,
        "complex": s.llm_deadline_complex_s,
        # IMAGE : génération potentiellement longue → même borne que complex.
        "image": s.llm_deadline_complex_s,
    }.get(name, s.llm_deadline_medium_s)


async def ainvoke_with_deadline(
    llm: Any,
    payload: Any,
    *,
    tier: Any = None,
    timeout_s: float | None = None,
    surface: str = "",
    config: dict | None = None,
):
    """``llm.ainvoke(payload)`` borné par une échéance murale.

    ``timeout_s`` explicite gagne ; sinon l'échéance du ``tier`` (défaut
    MEDIUM). ``surface`` est embarqué dans le message d'erreur pour le
    diagnostic (quel chemin a expiré) sans coût quand tout va bien.

    ``config`` est transmis tel quel à ``llm.ainvoke`` quand il est fourni, et
    OMIS sinon — les dizaines d'appels existants n'en passent pas et ne doivent
    rien voir changer. Son usage principal est ``{"callbacks": []}`` : un appel
    qui tourne PENDANT un tour actif doit couper l'arbre de callbacks, sinon
    LangChain le propage par contextvars et les tokens de cet appel s'affichent
    dans le stream de l'utilisateur (bug réel du 19/07/2026 : le code du
    générateur tier-S entrelacé caractère par caractère dans le chat).
    """
    t = float(timeout_s if timeout_s is not None else deadline_for_tier(tier))
    kwargs = {"config": config} if config is not None else {}
    try:
        return await asyncio.wait_for(llm.ainvoke(payload, **kwargs), timeout=t)
    except asyncio.TimeoutError:
        # « timed out » = mot-clé du mapping FailoverReason.TIMEOUT — ne pas
        # reformuler sans mettre à jour fallback_manager._REASON_KEYWORDS.
        raise TimeoutError(
            f"LLM call timed out after {t:.0f}s (wall-clock deadline"
            + (f", surface={surface}" if surface else "")
            + ")"
        ) from None
