# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_optional_args.py
# @brief      Incident 24/07 — les paramètres OPTIONNELS d'un outil MCP non
#             fournis par le modèle arrivaient à None et étaient refusés par
#             la validation de schéma, un par un.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Incident réel (24/07/2026, conversation de Gert).

« Traduis ce PDF en néerlandais » → l'outil MCP `translate_pdf_folder` a été
REFUSÉ 3 fois de suite en 10 secondes :

    ARGS={'input_dir': …, 'output_dir': …, 'target_language': 'nl',
          'layout': 'preserve'}
    ERROR=argument non conforme au schéma à « overwrite » (règle : type)

…alors que le modèle n'avait jamais passé `overwrite`. Cause :
``_json_schema_to_pydantic`` déclare tout champ non-requis
``Optional[T] = None`` ; LangChain matérialise le modèle Pydantic et passe
**tous** les champs en kwargs, y compris ceux laissés à None. La validation
JSON Schema voit alors ``overwrite: None`` contre ``{"type": "boolean"}`` et
refuse — puis ``ocr_language``, puis ``max_pages_per_pdf`` (jsonschema
s'arrête à la première erreur, d'où le tâtonnement du modèle).

Le contrat correct : **un optionnel non fourni est ABSENT**, pas null — sinon
on écrase aussi les valeurs par défaut du serveur. Sauf si le schéma autorise
explicitement null pour ce champ, auquel cas None est une valeur signifiante
qu'on doit transmettre.

Ce n'était pas propre au traducteur PDF : TOUT outil MCP avec des paramètres
optionnels typés était touché.

Run with:  cd backend && python -m pytest tests/test_mcp_optional_args.py -v
"""
from __future__ import annotations

import pytest

from app.services.mcp_schema import (
    MCPArgumentInvalid,
    strip_unset_optionals,
    validate_arguments,
)

# Le schéma RÉEL du serveur pdf-folder-translator (relevé en base le 24/07).
_PDF_SCHEMA = {
    "type": "object",
    "properties": {
        "input_dir": {"type": "string"},
        "output_dir": {"type": "string"},
        "target_language": {"type": "string", "default": "fr"},
        "layout": {"type": "string", "enum": ["text", "preserve"], "default": "text"},
        "overwrite": {"type": "boolean", "default": False},
        "ocr_language": {"type": "string", "default": "eng+fra"},
        "max_pages_per_pdf": {"type": "integer", "default": 0},
    },
    "required": ["input_dir", "output_dir"],
}

# Ce que LangChain envoie réellement quand le modèle ne fournit que 4 champs.
_LANGCHAIN_KWARGS = {
    "input_dir": "/app/uploads/u/x",
    "output_dir": "/app/uploads/u/x/NL",
    "target_language": "nl",
    "layout": "preserve",
    "overwrite": None,
    "ocr_language": None,
    "max_pages_per_pdf": None,
}


# ────────────────────────────────────────────────────────────────────────
# La régression elle-même
# ────────────────────────────────────────────────────────────────────────


def test_incident_reproduction_none_optionals_are_rejected():
    """Sans nettoyage, la charge exacte de l'incident est refusée."""
    with pytest.raises(MCPArgumentInvalid) as exc:
        validate_arguments(_PDF_SCHEMA, _LANGCHAIN_KWARGS)
    assert "overwrite" in str(exc.value)


def test_stripped_payload_passes_validation():
    """Après nettoyage, l'appel de Gert passe — du premier coup."""
    cleaned = strip_unset_optionals(_PDF_SCHEMA, _LANGCHAIN_KWARGS)
    validate_arguments(_PDF_SCHEMA, cleaned)  # ne lève pas
    assert cleaned == {
        "input_dir": "/app/uploads/u/x",
        "output_dir": "/app/uploads/u/x/NL",
        "target_language": "nl",
        "layout": "preserve",
    }


def test_stripping_preserves_falsy_values():
    """False / 0 / "" sont des valeurs CHOISIES par le modèle — jamais
    confondues avec « non fourni » (piège classique du `if not value`)."""
    cleaned = strip_unset_optionals(_PDF_SCHEMA, {
        "input_dir": "a", "output_dir": "b",
        "overwrite": False, "max_pages_per_pdf": 0, "ocr_language": "",
    })
    assert cleaned["overwrite"] is False
    assert cleaned["max_pages_per_pdf"] == 0
    assert cleaned["ocr_language"] == ""


def test_null_is_kept_when_the_schema_allows_it():
    """Un champ que le serveur déclare nullable garde son None — c'est une
    valeur signifiante, pas un oubli. Les trois formes JSON Schema."""
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": ["string", "null"]},
            "b": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "c": {"oneOf": [{"type": "integer"}, {"type": "null"}]},
            "d": {"type": "string"},
        },
    }
    cleaned = strip_unset_optionals(schema, {"a": None, "b": None, "c": None, "d": None})
    assert cleaned == {"a": None, "b": None, "c": None}  # d retiré, a/b/c gardés
    validate_arguments(schema, cleaned)  # ne lève pas


def test_required_none_is_kept_so_the_error_stays_honest():
    """Un REQUIS à None n'est pas silencieusement effacé : on le laisse pour
    que la validation dise « type », pas « required » — le modèle doit savoir
    qu'il a passé null, pas qu'il a oublié le champ."""
    cleaned = strip_unset_optionals(_PDF_SCHEMA, {"input_dir": None, "output_dir": "b"})
    assert cleaned["input_dir"] is None
    with pytest.raises(MCPArgumentInvalid):
        validate_arguments(_PDF_SCHEMA, cleaned)


def test_unknown_key_is_left_untouched():
    """Une clé hors schéma reste — le validateur tranche (additionalProperties)."""
    cleaned = strip_unset_optionals(_PDF_SCHEMA, {"input_dir": "a", "output_dir": "b",
                                                  "surprise": None})
    assert "surprise" in cleaned


def test_degrades_safely_without_schema():
    payload = {"x": None, "y": 1}
    assert strip_unset_optionals(None, payload) == payload
    assert strip_unset_optionals({}, payload) == payload
    assert strip_unset_optionals({"properties": "pas-un-dict"}, payload) == payload


def test_does_not_mutate_the_caller_payload():
    original = dict(_LANGCHAIN_KWARGS)
    strip_unset_optionals(_PDF_SCHEMA, _LANGCHAIN_KWARGS)
    assert _LANGCHAIN_KWARGS == original


# ────────────────────────────────────────────────────────────────────────
# Câblage : les DEUX chemins d'appel MCP nettoient avant validation ET
# avant l'envoi au serveur (un null explicite écraserait son défaut).
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrap_call_cleans_before_validating_and_calling():
    from app.services.mcp_client import _wrap_call

    seen: dict = {}

    async def _caller(args):
        seen.update(args)
        class _R:
            content = []
            isError = False
        return _R()

    call = _wrap_call("mcp__pdf__translate", _PDF_SCHEMA, _caller)
    out = await call(**_LANGCHAIN_KWARGS)

    assert "Erreur MCP" not in out, "l'appel de Gert doit passer du premier coup"
    # Le serveur ne reçoit PAS de null : il applique ses propres défauts.
    assert "overwrite" not in seen
    assert "ocr_language" not in seen
    assert "max_pages_per_pdf" not in seen
    assert seen["target_language"] == "nl"
    assert seen["layout"] == "preserve"


@pytest.mark.asyncio
async def test_remote_call_tool_cleans_too(monkeypatch):
    """Le chemin distant (remote_call_tool) partage la garde."""
    import app.services.mcp_remote as mod

    seen: dict = {}

    class _Session:
        async def call_tool(self, name, args):
            seen.update(args)
            class _R:
                content = []
                isError = False
            return _R()

    class _Ctx:
        async def __aenter__(self):
            return _Session()
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod, "_session", lambda *a, **k: _Ctx())

    async def _headers(_uid, _srv):
        return None

    monkeypatch.setattr("app.services.mcp_credentials.resolve_user_headers", _headers)

    class _Srv:
        url = "https://example.test/mcp"
        transport = "streamable_http"
        allow_private_network = False

    await mod.remote_call_tool(
        _Srv(), "u1", "translate_pdf_folder", dict(_LANGCHAIN_KWARGS),
        input_schema=_PDF_SCHEMA, local_name="mcp__pdf__translate",
    )
    assert "overwrite" not in seen
    assert seen["layout"] == "preserve"
