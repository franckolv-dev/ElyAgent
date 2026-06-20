# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_schema.py
# @brief      Validation des arguments MCP contre le JSON Schema COMPLET.
# @license    Elastic License 2.0
# =============================================================================
"""Validation d'arguments sans perte + hash de définition d'outil.

Le wrapper LangChain expose au modèle un modèle Pydantic simplifié, mais
l'appel réel doit être validé contre le **JSON Schema complet** du serveur,
et refusé localement s'il n'est pas conforme — *sans contacter le serveur*
(cadrage §8.7). On utilise ``jsonschema`` (déjà en dépendance).
"""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class MCPArgumentInvalid(Exception):
    """Arguments hors schéma. ``code`` stable, sans secret."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "MCP_ARGUMENT_INVALID"


def validate_arguments(schema: dict | None, arguments: dict) -> None:
    """Valide ``arguments`` contre le JSON Schema ``schema``.

    Lève ``MCPArgumentInvalid`` si non conforme. Si le schéma est absent ou
    lui-même invalide, on n'échoue PAS l'appel (on ne peut pas valider) — on
    journalise et on laisse passer ; la validation ne doit pas devenir un déni
    de service sur un schéma serveur pathologique."""
    if not schema or not isinstance(schema, dict):
        return
    try:
        import jsonschema
    except ImportError:  # pragma: no cover — jsonschema est en dépendance
        return
    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
    except Exception as exc:
        logger.debug("MCP input schema invalide, validation ignorée : %s", exc)
        return
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as exc:
        # Message court et stable. On N'INCLUT PAS ``exc.message`` : il embarque
        # la valeur fautive (ex. « 'ghp_secret' is not of type… ») → fuite PII/
        # secret vers le modèle et les logs. On ne donne que le chemin + la
        # règle violée.
        path = "/".join(str(p) for p in exc.absolute_path) or "(racine)"
        raise MCPArgumentInvalid(
            f"argument non conforme au schéma à « {path} » (règle : {exc.validator})"
        ) from None


def definition_hash(
    remote_name: str,
    description: str | None,
    input_schema: dict | None,
    output_schema: dict | None,
) -> str:
    """Empreinte stable d'une définition d'outil (détection de changement).

    Un changement de nom, description ou schéma invalide les autorisations qui
    dépendaient de l'ancienne définition (cadrage §14.2)."""
    payload = json.dumps(
        {
            "name": remote_name,
            "description": description or "",
            "input": input_schema or {},
            "output": output_schema or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
