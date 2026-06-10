# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_learned_tool_exec.py
# @brief      Sprint 4d J1 — regression : un python_tool VALIDÉ se compile et
#             S'EXÉCUTE. Manque relevé par l'audit V4 : le scénario S couvrait
#             la surface API (list/pin/forget), jamais l'exécution réelle.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario — learned python_tool : validate → compile → invoke.

Pin du contrat runtime sur lequel la graduation (V4) s'appuie : si la
chaîne validation 7 étages → compile_tool_source → StructuredTool.invoke
casse, un outil « éprouvé » n'est plus reproductible et toute graduation
serait bâtie sur du sable. Source FIXE (pas de LLM — tag shallow).
"""
from __future__ import annotations

NAME = "learned python_tool : validate → compile → invoke"
DESCRIPTION = (
    "Une source python_tool canonique (scaffold @register+@tool du "
    "générateur V2, imports stdlib only) passe la validation, se compile "
    "en StructuredTool et s'invoque avec le bon résultat. Pin aussi le "
    "rejet d'une source hors allow-list (import os)."
)
TAGS = ["shallow"]

# Scaffold canonique du générateur V2 (tool_generator._SYSTEM_PROMPT) :
# imports stdlib autorisés uniquement, @register strippé à la compilation.
_GOOD_SOURCE = '''
from __future__ import annotations

import statistics

from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="bench_median_ms",
    skill_display_name="Median latency",
    skill_description="Median of a list of latencies in ms.",
    skill_icon="🧮",
    enabled_by_default=False,
)
@tool
def bench_median_ms(values: str) -> str:
    """Compute the median of comma-separated latency values in ms."""
    parsed = [float(v.strip()) for v in values.split(",") if v.strip()]
    if not parsed:
        return "no values"
    return str(statistics.median(parsed))
'''

# Même scaffold, import interdit — code_guard DOIT refuser.
_BAD_SOURCE = _GOOD_SOURCE.replace("import statistics", "import os")


async def run() -> dict:
    from app.services.learning.tool_loader import compile_tool_source
    from app.services.learning.tool_orchestrator import validate_tool_source
    from bench.scenarios._base import from_checks

    report = validate_tool_source(
        _GOOD_SOURCE,
        existing_names=frozenset(),
        run_smoke=True,
        smoke_kwargs={"values": "3, 1, 2"},
    )

    loaded = compile_tool_source(_GOOD_SOURCE)
    invoked = None
    if loaded.ok and loaded.tool is not None:
        invoked = loaded.tool.invoke({"values": "10, 30, 20"})

    bad_report = validate_tool_source(
        _BAD_SOURCE,
        existing_names=frozenset(),
        run_smoke=False,
    )

    return from_checks({
        "validation_passes": bool(report.ok),
        "compile_ok": bool(loaded.ok),
        "tool_name_bound": loaded.name == "bench_median_ms",
        "invoke_returns_median": str(invoked) == "20.0",
        "forbidden_import_rejected": not bad_report.ok,
    })
