# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/ws_registry.py
# @brief      Global registry of active WebSocket connections, keyed by user_id
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Global registry of active WebSocket connections, keyed by user_id.

Used by the HITL manager to push real-time status updates to the browser
while the agent is waiting for Android validation.
"""
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)
_registry: dict[str, WebSocket] = {}


def register(user_id: str, ws: WebSocket) -> None:
    if user_id in _registry:
        logger.debug("Replacing existing WebSocket for user %s", user_id)
    _registry[user_id] = ws


def unregister(user_id: str) -> None:
    if _registry.pop(user_id, None) is not None:
        logger.debug("Unregistered WebSocket for user %s", user_id)


def get(user_id: str) -> WebSocket | None:
    return _registry.get(user_id)
