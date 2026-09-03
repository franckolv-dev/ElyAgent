# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_schema.py
# @brief      J3 — validation d'arguments sans perte + hash de définition.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
from __future__ import annotations

import pytest

from app.services.mcp_schema import (
    MCPArgumentInvalid,
    definition_hash,
    validate_arguments,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1},
        "mode": {"type": "string", "enum": ["fast", "deep"]},
    },
    "required": ["q"],
}


def test_valid_args_pass():
    validate_arguments(_SCHEMA, {"q": "hello", "limit": 5, "mode": "fast"})  # no raise


def test_wrong_type_rejected_without_server():
    with pytest.raises(MCPArgumentInvalid):
        validate_arguments(_SCHEMA, {"q": 123})


def test_missing_required_rejected():
    with pytest.raises(MCPArgumentInvalid):
        validate_arguments(_SCHEMA, {"limit": 2})


def test_enum_violation_rejected():
    with pytest.raises(MCPArgumentInvalid):
        validate_arguments(_SCHEMA, {"q": "x", "mode": "turbo"})


def test_nested_schema_not_flattened():
    """Un objet imbriqué requis est validé en profondeur (sans perte)."""
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
        "required": ["user"],
    }
    validate_arguments(schema, {"user": {"id": 7}})  # ok
    with pytest.raises(MCPArgumentInvalid):
        validate_arguments(schema, {"user": {"id": "not-int"}})


def test_none_or_empty_schema_skips():
    validate_arguments(None, {"anything": 1})
    validate_arguments({}, {"anything": 1})


def test_malformed_schema_does_not_dos_the_call():
    """Un schéma serveur pathologique ne doit PAS bloquer tous les appels."""
    validate_arguments({"type": "object", "properties": 12345}, {"x": 1})  # no raise


def test_error_message_has_no_value_dump():
    """Le message d'erreur ne doit pas divulguer la valeur fautive (PII/secret).

    jsonschema embarque la valeur dans son message ; on doit la masquer."""
    secret = "ghp_SUPER_SECRET_TOKEN"
    with pytest.raises(MCPArgumentInvalid) as exc:
        # `mode` n'accepte que fast|deep → violation enum, valeur = le secret.
        validate_arguments(_SCHEMA, {"q": "x", "mode": secret})
    assert secret not in str(exc.value)
    assert "mode" in str(exc.value)  # le chemin reste utile


def test_definition_hash_stable_and_sensitive():
    a = definition_hash("search", "Search", {"type": "object"}, None)
    b = definition_hash("search", "Search", {"type": "object"}, None)
    assert a == b
    # Tout changement de définition change le hash.
    assert a != definition_hash("search", "Search v2", {"type": "object"}, None)
    assert a != definition_hash("search", "Search", {"type": "string"}, None)
