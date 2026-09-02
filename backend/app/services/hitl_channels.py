# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/hitl_channels.py
# @brief      Canaux de notification HITL acceptés — source unique
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Liste blanche des canaux de notification HITL, et sa normalisation.

⚠️ POURQUOI CE MODULE EXISTE (02/09/2026). La liste vivait dans
``app.routers.hitl_prefs``, qui importe ``app.services.hitl_manager`` : le
dispatch ne pouvait donc pas la lire sans créer un cycle d'import. Il lisait
la colonne BRUTE, et une préférence orpheline (« discord », « slack », retirés
avec leurs canaux) sortait avec un éventail VIDE — l'utilisateur n'était
prévenu que par le WebSocket. Sur un chemin sans navigateur (mission, tâche
planifiée), il n'était prévenu par rien et la demande expirait en auto-refus.

Un garde-fou de sécurité qui se tait est pire qu'absent : on croit le tenir.
Le routeur ET le dispatch normalisent maintenant depuis ce même endroit.
"""
from __future__ import annotations

# Valeurs acceptées. À garder en phase avec le menu déroulant des Réglages.
ALLOWED_CHANNELS = frozenset({
    "ely_android",
    "ntfy",
    "telegram",
    "web_only",
    "all",
})

# Comportement historique : rien de posé = diffusion à tous les canaux liés.
DEFAULT_CHANNEL = "all"


def normalize_channel(value: str | None) -> str:
    """Rend un canal servable : un nom inconnu retombe sur ``all``.

    C'est le seul chemin de lecture autorisé pour
    ``User.hitl_preferred_channel``. Une valeur laissée en base par un canal
    depuis retiré n'a plus d'envoyeur : la traiter telle quelle revient à ne
    prévenir personne, alors que le sens de la préférence était « préviens-moi
    ailleurs que dans le navigateur ».
    """
    canal = (value or DEFAULT_CHANNEL).strip().lower()
    return canal if canal in ALLOWED_CHANNELS else DEFAULT_CHANNEL
