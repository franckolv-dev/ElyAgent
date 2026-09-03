# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/turn_ledger.py
# @brief      Registre de tour (C3d-3) — résultats d'outils du tour courant,
#             par conversation, pour le fallback HONNÊTE du superviseur.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Registre de tour — les résultats d'outils déjà acquis dans le tour courant.

Pourquoi (exhibits 18/07/2026, ×4) : quand un sous-agent meurt APRÈS avoir
exécuté ses outils (ex. gmail_list_emails réussi puis synthèse LLM en panne),
le fallback général repartait de zéro — l'état interne du subgraph est perdu
avec l'exception — et confabulait « l'accès à ta boîte Gmail n'est pas
disponible » alors que le résultat était déjà là.

La passerelle (`tool_gateway.execute_tool_call`) enregistre ici chaque
résultat d'outil RÉUSSI (version ANONYMISÉE — c'est ce qu'un LLM cloud a le
droit de voir), keyé par conversation. Le `router_node` vide l'entrée au
début de chaque tour utilisateur ; le fallback du superviseur lit les
entrées pour construire un avis « échec technique » qui interdit au modèle
de secours d'inventer un problème d'accès et lui donne les résultats déjà
acquis.

Mémoire process uniquement, borné (LRU conversations + N entrées/conv +
troncature par entrée) — même philosophie que `conversation_filters`.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)

_MAX_CONVERSATIONS = 512   # LRU — au-delà, la conversation la plus ancienne saute
_MAX_ENTRIES = 24          # par conversation — un tour outillé normal en fait < 10
_MAX_RESULT_CHARS = 400    # tête du résultat — assez pour réutiliser, borne le prompt

_lock = threading.Lock()
_ledger: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()


def record(conversation_id: str, tool_name: str, result: object) -> None:
    """Mémorise (outil, tête du résultat) pour le tour courant. Jamais bloquant."""
    if not conversation_id or not tool_name:
        return
    try:
        head = str(result or "")[:_MAX_RESULT_CHARS]
        with _lock:
            entries = _ledger.setdefault(conversation_id, [])
            if len(entries) < _MAX_ENTRIES:
                entries.append((tool_name, head))
            _ledger.move_to_end(conversation_id)
            while len(_ledger) > _MAX_CONVERSATIONS:
                _ledger.popitem(last=False)
    except Exception as exc:  # noqa: BLE001 — le registre ne casse jamais un appel
        logger.debug("turn_ledger.record skipped: %s", exc)


def entries(conversation_id: str) -> list[tuple[str, str]]:
    """Résultats d'outils du tour courant (copie)."""
    with _lock:
        return list(_ledger.get(conversation_id, ()))


def clear(conversation_id: str) -> None:
    """Nouveau tour utilisateur → registre vierge pour cette conversation."""
    if not conversation_id:
        return
    with _lock:
        _ledger.pop(conversation_id, None)


def technical_failure_notice(
    domain: str, reason: str, acquired: list[tuple[str, str]],
) -> str:
    """Texte injecté (SystemMessage) au général de secours après un échec
    de sous-agent — les DEUX consignes qui manquaient le 18/07 :
    l'échec est TECHNIQUE (pas un problème d'accès), et voilà ce qui est
    déjà acquis (à réutiliser, pas à re-payer)."""
    lines = [
        f"⚠️ Le spécialiste « {domain} » vient d'échouer pour une raison "
        f"PUREMENT TECHNIQUE ({reason}) — panne du fournisseur LLM ou "
        "délai dépassé. Ce n'est NI un problème d'accès, NI de permissions, "
        "NI un outil manquant : n'affirme JAMAIS que l'accès est "
        "indisponible à cause de cet échec.",
    ]
    if acquired:
        lines.append(
            "Résultats d'outils DÉJÀ OBTENUS pendant ce tour — réutilise-les "
            "directement au lieu de rappeler les mêmes outils :"
        )
        lines += [f"  • {tool} → {head}" for tool, head in acquired]
        lines.append(
            "Réponds maintenant à la demande initiale de l'utilisateur à "
            "partir de ces résultats (complète par un appel d'outil seulement "
            "si une information manque)."
        )
    else:
        lines.append(
            "Aucun résultat d'outil n'avait encore été obtenu : réessaie "
            "toi-même les outils nécessaires pour répondre à la demande."
        )
    return "\n".join(lines)
