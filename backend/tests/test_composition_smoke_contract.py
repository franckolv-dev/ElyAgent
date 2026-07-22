# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_composition_smoke_contract.py
# @brief      Garde de contrat : un tool composé qui traite le retour de
#             call_tool comme un dict/une liste est REFUSÉ à la validation.
# =============================================================================
"""Incident 22/07 — pourquoi cette garde existe.

`convert_pdf_to_docx`, généré puis promu, faisait :

    files = await call_tool("drive_list_files", {...})
    pdf_id = files[0].get("id")     # ← 'str' object has no attribute 'get'

Tous les tools d'Ely renvoient du TEXTE lisible, jamais des dicts. Le tool
a franchi ast + ruff + mypy + registration sans encombre, parce que le stage
smoke était purement et simplement SAUTÉ pour les tools composés — aucun tool
de composition n'était donc jamais exécuté avant promotion. Il a été promu,
appelé 5 fois, et a échoué 5 fois en production.

La garde ci-dessous exécute les tools composés contre un `call_tool` stubbé
qui renvoie une CHAÎNE réaliste, et refuse ceux qui la maltraitent. Le stub
ne peut pas valider la logique métier — il valide le CONTRAT DE TYPE, qui
est exactement ce qui a cassé.
"""
from __future__ import annotations

from app.services.learning.smoke_sandbox import smoke_run
from app.services.learning.tool_orchestrator import validate_tool_source

_HEADER = """\
from __future__ import annotations

from langchain_core.tools import tool

from app.services.learning.learned_tool_dispatch import call_tool
from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="{name}",
    skill_display_name="X",
    skill_description="One sentence.",
    skill_icon="🧩",
    enabled_by_default=False,
)
@tool
async def {name}(query: str) -> str:
    \"\"\"Docstring qui dit quand appeler ce tool.\"\"\"
"""


def _tool_source(body: str, name: str = "t_compose") -> str:
    return _HEADER.format(name=name) + body


def _validate(source: str):
    return validate_tool_source(
        source, existing_names=frozenset(), smoke_kwargs={"query": "x"}
    )


def _stage(report, name: str):
    return next((s for s in report.stages if s.stage == name), None)


# ── Le stub doit imiter le vrai contrat : une chaîne ─────────────────────────
def test_call_tool_stub_returns_a_string_not_a_dict():
    source = _tool_source(
        "    res = await call_tool('drive_list_files', {'query': query})\n"
        "    return type(res).__name__\n"
    )

    report = smoke_run(source, kwargs={"query": "x"})

    assert report.ok, report.detail
    assert "str" in report.result_repr


# ── Le bug exact de l'incident doit être refusé ──────────────────────────────
def test_treating_result_as_a_list_of_dicts_is_rejected():
    source = _tool_source(
        "    files = await call_tool('drive_list_files', {'query': query})\n"
        "    if not files or len(files) == 0:\n"
        "        return 'not found'\n"
        "    return str(files[0].get('id'))\n"
    )

    report = _validate(source)

    assert not report.ok
    assert report.failed_stage == "smoke"
    smoke = _stage(report, "smoke")
    assert "AttributeError" in smoke.detail


def test_calling_get_on_the_result_is_rejected():
    source = _tool_source(
        "    res = await call_tool('drive_list_files', {'query': query})\n"
        "    return str(res.get('id'))\n"
    )

    report = _validate(source)

    assert not report.ok
    assert report.failed_stage == "smoke"


def test_json_loads_on_the_result_is_rejected():
    source = (
        "from __future__ import annotations\n\nimport json\n"
        + _tool_source(
            "    res = await call_tool('drive_list_files', {'query': query})\n"
            "    return str(json.loads(res))\n"
        ).split("from __future__ import annotations\n", 1)[1]
    )

    report = _validate(source)

    assert not report.ok
    assert report.failed_stage == "smoke"


# ── Un tool correct passe ────────────────────────────────────────────────────
def test_text_parsing_composition_is_accepted():
    source = (
        "from __future__ import annotations\n\nimport re\n"
        + _tool_source(
            "    listing = await call_tool('drive_list_files', {'query': query})\n"
            "    if 'Aucun' in listing or listing.startswith('Erreur'):\n"
            "        return 'rien trouve'\n"
            "    found = re.search(r'ID\\\\s*:\\\\s*(\\\\S+)', listing)\n"
            "    return found.group(1) if found else 'id introuvable'\n"
        ).split("from __future__ import annotations\n", 1)[1]
    )

    report = _validate(source)

    assert report.ok, report.failed_stage
    smoke = _stage(report, "smoke")
    assert smoke is not None and smoke.ok


def test_missing_sample_input_is_not_a_contract_breach():
    """Sans smoke_kwargs, le bac à sable appelle la fonction sans argument.

    Le TypeError qui en résulte vient de la SIGNATURE, pas du contrat de
    call_tool : recaler le tool là-dessus rejetterait tout appelant qui ne
    fournit pas d'échantillon d'entrée (cf. test_composition_runtime).
    """
    source = _tool_source(
        "    listing = await call_tool('drive_list_files', {'query': query})\n"
        "    return listing[:10]\n"
    )

    report = validate_tool_source(source, existing_names=frozenset())

    assert report.ok, report.to_json()
    assert _stage(report, "smoke").ok


def test_pure_tool_is_unaffected():
    """Non-régression : les tools purs gardent leur smoke d'origine."""
    source = """\
from __future__ import annotations

from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="t_pure",
    skill_display_name="X",
    skill_description="One sentence.",
    skill_icon="🧩",
    enabled_by_default=False,
)
@tool
def t_pure(x: int) -> int:
    \"\"\"Double x.\"\"\"
    return x * 2
"""

    report = validate_tool_source(
        source, existing_names=frozenset(), smoke_kwargs={"x": 3}
    )

    assert report.ok, report.failed_stage
    assert _stage(report, "smoke").ok
