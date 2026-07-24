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


def _schema_allows_null(prop_schema: dict) -> bool:
    """Le schéma d'une propriété accepte-t-il explicitement ``null`` ?

    Trois formes JSON Schema : ``{"type": "null"}``, ``{"type": [... "null"]}``
    et ``anyOf``/``oneOf`` contenant une branche null. Quand c'est le cas,
    ``None`` est une valeur SIGNIFIANTE choisie par le modèle — on la transmet.
    """
    if not isinstance(prop_schema, dict):
        return False
    t = prop_schema.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return True
    for key in ("anyOf", "oneOf"):
        branches = prop_schema.get(key)
        if isinstance(branches, list) and any(
            _schema_allows_null(b) for b in branches if isinstance(b, dict)
        ):
            return True
    return False


def strip_unset_optionals(schema: dict | None, arguments: dict) -> dict:
    """Retire les optionnels laissés à ``None`` — « non fourni » ≠ ``null``.

    Pourquoi (incident 24/07) : ``_json_schema_to_pydantic`` déclare tout
    champ non-requis ``Optional[T] = None``, et LangChain matérialise le
    modèle Pydantic — il passe donc TOUS les champs en kwargs, y compris ceux
    que le modèle n'a jamais remplis. La validation JSON Schema voyait alors
    ``overwrite: None`` contre ``{"type": "boolean"}`` et refusait l'appel,
    champ après champ (jsonschema s'arrête à la première erreur) : le modèle
    devait deviner les optionnels un par un pour être enfin autorisé à
    travailler. Transmettre ``null`` serait faux de toute façon — ça écrase
    la valeur par défaut du serveur.

    Ne retire QUE ce qui est sûr :
      - la clé est déclarée dans ``properties`` (sinon on laisse le validateur
        trancher — ``additionalProperties`` peut l'interdire) ;
      - le schéma de la propriété n'autorise pas ``null`` ;
      - la clé n'est pas ``required`` (un requis à None doit produire une
        erreur de TYPE honnête, pas se transformer en « champ manquant »).

    Les valeurs falsy (``False``, ``0``, ``""``) sont des choix explicites du
    modèle : elles ne sont jamais retirées. Ne modifie pas l'entrée.
    """
    if not isinstance(arguments, dict):
        return arguments
    if not schema or not isinstance(schema, dict):
        return dict(arguments)
    props = schema.get("properties")
    if not isinstance(props, dict):
        return dict(arguments)
    required = schema.get("required")
    required = set(required) if isinstance(required, list) else set()

    cleaned = {}
    for key, value in arguments.items():
        if (
            value is None
            and key in props
            and key not in required
            and not _schema_allows_null(props.get(key, {}))
        ):
            continue
        cleaned[key] = value
    return cleaned


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
