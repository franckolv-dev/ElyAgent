# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/google_raw_api.py
# @brief      Shared helpers for the Google raw_api_call escape-hatch tools.
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
"""Shared helpers for the Google `*_raw_api_call` tools.

Each Google API tool exposes a `{service}_raw_api_call` escape hatch so the
LLM can reach parts of the Google API that are not covered by a dedicated
typed tool. These helpers resolve method paths on a googleapiclient Resource
and format the response uniformly.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_BLOCKED_METHODS = frozenset({
    "users.messages.batchDelete",
    "files.emptyTrash",
    "calendars.delete",
    "users.settings.forwardingAddresses.create",
    "users.settings.delegates.create",
})


def resolve_google_method(service: Any, method_path: str) -> Any:
    """Walk a dot-separated method path on a googleapiclient Resource.

    Example paths:
      - "spreadsheets.batchUpdate"
      - "spreadsheets.values.get"
      - "users.messages.batchModify"
      - "files.permissions.create"

    Intermediate segments are zero-arg method calls that return a sub-resource;
    the final segment is returned unbound so the caller passes kwargs + body
    then calls `.execute()` on the returned request object.
    """
    parts = [p for p in method_path.strip().split(".") if p]
    if not parts:
        raise ValueError("method_path vide")
    obj = service
    for segment in parts[:-1]:
        attr = getattr(obj, segment, None)
        if attr is None or not callable(attr):
            raise AttributeError(
                f"segment inconnu '{segment}' dans '{method_path}'"
            )
        obj = attr()
    final_attr = getattr(obj, parts[-1], None)
    if final_attr is None or not callable(final_attr):
        raise AttributeError(
            f"méthode inconnue '{parts[-1]}' dans '{method_path}'"
        )
    return final_attr


def execute_raw_call(
    service: Any,
    method_path: str,
    params_json: str,
    body_json: str,
    service_label: str,
) -> str:
    """Parse JSON params/body, resolve the method and execute.

    Returns a user-facing string (successful truncated JSON, or a clear
    error message starting with "Erreur"). Logs enough context for audit.
    """
    if method_path in _BLOCKED_METHODS:
        return f"❌ Méthode '{method_path}' bloquée par sécurité. Utilise les outils dédiés."

    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError as e:
        return f"Erreur : params_json doit être un JSON valide. Détail : {e}"
    if not isinstance(params, dict):
        return "Erreur : params_json doit être un objet JSON."

    if body_json.strip():
        try:
            params["body"] = json.loads(body_json)
        except json.JSONDecodeError as e:
            return f"Erreur : body_json doit être un JSON valide. Détail : {e}"

    try:
        method = resolve_google_method(service, method_path)
        logger.info(
            "%s_raw_api_call: %s params_keys=%s",
            service_label, method_path, list(params.keys()),
        )
        result = method(**params).execute()
    except Exception as e:
        logger.error(
            "%s_raw_api_call failed on %s: %s",
            service_label, method_path, e,
        )
        return f"Erreur {service_label}_raw_api_call ({method_path}) : {e}"

    try:
        output = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except Exception:
        output = str(result)
    if len(output) > 4000:
        output = output[:4000] + "\n... (tronqué)"
    return f"✓ {method_path} ok\n{output}"
