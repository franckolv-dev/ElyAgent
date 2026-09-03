# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_orchestrator.py
# @brief      Sprint 4b V2 J6 — validation-chain orchestrator: runs the 5
#             pipeline stages over a generated @tool source, fail-fast.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""The thing that turns J2-J5 into a pipeline (design note J0 §3.3).

``validate_tool_source`` runs the 5 stages in order, **fail-fast**:

    [1] code_guard  (AST allow-list)        — security
    [2] ruff        (lint, F821 undefined)  — static
    [3] mypy        (type consistency)       — static
    [4] smoke       (run once under limits)  — dynamic
    [5] registration (collision / bindable)  — registry safety

The first stage to fail stops the chain and is named in the report. The
report serialises to JSON for ``LearnedSkill.validation_report_json`` and
feeds back into the generator's next iteration (J6 generator / J7 loop).

Pure: no LLM, no DB, no global mutation. The caller passes the set of
existing tool names (for the collision check) and a sample ``smoke_kwargs``
(so stage 4 can actually call the function). Smoke can be skipped when no
sample input is available.

Precondition reminder: stage 1 (code_guard) MUST run first — the smoke
sandbox's network safety relies on guard-passed source (J0 §3.2).
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from typing import Literal

from app.services.learning.code_guard import GuardProfile, check_tool_source
from app.services.learning.registration_gate import check_registration_safety
from app.services.learning.smoke_sandbox import SmokeReport, smoke_run
from app.services.learning.static_checks import run_mypy, run_ruff
from app.services.learning.v3_declarations import (
    check_declarations_wellformed,
    check_deps_subset_of_baked,
    parse_v3_declarations,
)


# ── Report types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageResult:
    # Profile=pure:  ast | ruff | mypy | smoke | registration
    # Profile=io:    ast | declarations | deps | ruff | mypy | smoke | registration
    stage: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ToolValidationReport:
    ok: bool
    failed_stage: str | None = None
    tool_name: str | None = None
    stages: tuple[StageResult, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "failed_stage": self.failed_stage,
            "tool_name": self.tool_name,
            "stages": [
                {"stage": s.stage, "ok": s.ok, "detail": s.detail} for s in self.stages
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def summary(self) -> str:
        if self.ok:
            return f"ok ({len(self.stages)} stages passed)"
        return f"failed at {self.failed_stage}: " + next(
            (s.detail for s in self.stages if not s.ok), ""
        )


# ── The chain ────────────────────────────────────────────────────────────────

STAGE_ORDER = ("ast", "ruff", "mypy", "smoke", "registration")

# Sprint 4b V3 J5 — when profile="io", the V3 declaration gates run between
# the AST guard and ruff. Order matters: code_guard catches the dangerous
# patterns first; once we know the source is structurally safe, we audit
# what it CLAIMS to need (declarations) before paying for ruff/mypy/smoke.
STAGE_ORDER_IO = ("ast", "declarations", "deps", "ruff", "mypy", "smoke", "registration")


def _composes_tools(source: str) -> bool:
    """True if ``source`` calls ``call_tool(...)`` — i.e. it composes other
    ELY tools (vs a pure-computation tool). Selects the NARROW smoke stage:
    the sandbox can't reach the real tools, so it validates the call_tool
    type contract rather than the composition's semantics."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "call_tool" in source
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "call_tool"
        for node in ast.walk(tree)
    )


# Exceptions qui signent le mésusage du retour de call_tool : le tool a
# traité une CHAÎNE comme un dict / une liste / du JSON.
#   AttributeError → .get(), .keys(), .items() sur une str
#   TypeError      → res["clé"] (indices str), itération de dicts…
#   KeyError       → res["clé"] après un json.loads imaginaire
#   IndexError     → res[3] hors de la chaîne stub
#   JSONDecodeError→ json.loads(prose)  (sous-classe de ValueError)
_CONTRACT_EXCEPTIONS = (
    "AttributeError",
    "TypeError",
    "KeyError",
    "IndexError",
    "JSONDecodeError",
)


# TypeError de SIGNATURE : le bac à sable a appelé la fonction sans (ou avec
# de mauvais) ``smoke_kwargs``. C'est un défaut d'échantillon d'entrée, pas un
# mésusage du retour de call_tool — ne jamais recaler le tool là-dessus.
_SIGNATURE_TYPEERROR_MARKERS = (
    "required positional argument",
    "required keyword-only argument",
    "unexpected keyword argument",
    "positional arguments but",
    "takes no arguments",
)


def _contract_breach(smoke: SmokeReport) -> str | None:
    """Message d'échec si ``smoke`` révèle un mésusage du contrat de type,
    ``None`` sinon (y compris pour un échec sémantique, hors de portée ici).
    """
    if smoke.outcome != "raised":
        return None
    detail = smoke.detail or ""
    exc_type = detail.split(":", 1)[0].strip()
    if exc_type not in _CONTRACT_EXCEPTIONS:
        return None
    if exc_type == "TypeError" and any(
        marker in detail for marker in _SIGNATURE_TYPEERROR_MARKERS
    ):
        return None
    return (
        f"contrat call_tool violé — {detail.strip()}. "
        "call_tool renvoie une chaîne lisible (str), jamais un dict/une "
        "liste/du JSON : analyse le texte (re, in, splitlines) au lieu de "
        ".get() / [0] / json.loads()."
    )


def validate_tool_source(
    source: str,
    *,
    existing_names: set[str] | frozenset[str],
    smoke_kwargs: dict | None = None,
    run_smoke: bool = True,
    profile: GuardProfile = "pure",
) -> ToolValidationReport:
    """Run the validation chain over ``source``, fail-fast.

    Returns a :class:`ToolValidationReport`. The chain stops at the first
    failing stage; later stages are not run (and not listed).

    ``profile`` (Sprint 4b V3 J5):
        - ``"pure"`` (default) — V2 N1/N2 scope, 5 stages: ast → ruff → mypy
          → smoke → registration. Backward-compatible with every existing
          caller; the new V3 gates are NOT run.
        - ``"io"`` — V3 scope, 7 stages: adds ``declarations`` and ``deps``
          between ``ast`` and ``ruff``. The AST guard itself uses the wider
          allow-list (httpx / bs4 / lxml). The ``secrets_exist`` gate is
          NOT in this chain because it's async + needs a user_id — it's
          called separately by the runtime dispatcher in J6.

    ``run_smoke`` can be False when no sample input is available for the
    smoke stage.
    """
    stages: list[StageResult] = []

    def _finish(failed: str | None, tool_name: str | None = None) -> ToolValidationReport:
        return ToolValidationReport(
            ok=failed is None,
            failed_stage=failed,
            tool_name=tool_name,
            stages=tuple(stages),
        )

    # [1] AST allow-list (security) — MUST be first. The profile flag here
    # widens the import allow-list when profile="io" (J3); FORBIDDEN_CALLS
    # and dunder access are still banned in both profiles.
    guard = check_tool_source(source, profile=profile)
    stages.append(StageResult("ast", guard.ok, guard.summary()))
    if not guard.ok:
        return _finish("ast")

    # [1.5] V3 declaration gates — only when profile="io". A tool that
    # declares nothing (V3Declarations.is_pure) passes both vacuously, so a
    # composition or pure-compute tool routed through profile="io" by mistake
    # doesn't get spurious failures. Run BEFORE ruff/mypy/smoke so we fail
    # fast on bad declarations without paying for the heavier static checks.
    if profile == "io":
        decls = parse_v3_declarations(source)
        wellformed = check_declarations_wellformed(source, decls=decls)
        stages.append(StageResult("declarations", wellformed.ok, wellformed.summary()))
        if not wellformed.ok:
            return _finish("declarations")

        deps = check_deps_subset_of_baked(decls)
        stages.append(StageResult("deps", deps.ok, deps.summary()))
        if not deps.ok:
            return _finish("deps")

    # [2] ruff
    ruff = run_ruff(source)
    stages.append(StageResult("ruff", ruff.ok, ruff.summary()))
    if not ruff.ok:
        return _finish("ruff")

    # [3] mypy
    mypy = run_mypy(source)
    stages.append(StageResult("mypy", mypy.ok, mypy.summary()))
    if not mypy.ok:
        return _finish("mypy")

    # [4] smoke (dynamic) — optional when no sample input is available.
    #
    # Composition tools get a NARROWER smoke (incident 22/07). The sandbox
    # still can't reach the real ELY tools, so it cannot validate composition
    # SEMANTICS — but the stubbed `call_tool` returns a realistic str, which
    # is enough to validate the TYPE CONTRACT. Skipping smoke entirely (the
    # previous behaviour) let `convert_pdf_to_docx` reach production with
    # `files[0].get("id")` on a string: promoted, then 5 crashes in a row.
    #
    # Only contract violations fail the stage. A composition tool that
    # raises for a semantic reason against a stub (a real ID it can't find,
    # an assumption the fake listing doesn't satisfy) is NOT a defect we can
    # judge here, so it passes with a note.
    if _composes_tools(source):
        if run_smoke:
            smoke = smoke_run(source, kwargs=smoke_kwargs or {})
            breach = _contract_breach(smoke)
            stages.append(
                StageResult(
                    "smoke",
                    breach is None,
                    breach
                    or f"composition contract ok ({smoke.outcome}); "
                    "semantics validated live, not in sandbox",
                )
            )
            if breach is not None:
                return _finish("smoke")
        else:
            stages.append(
                StageResult("smoke", True, "skipped: no sample input for composition tool")
            )
    elif run_smoke:
        smoke = smoke_run(source, kwargs=smoke_kwargs or {})
        stages.append(
            StageResult("smoke", smoke.ok, f"{smoke.outcome}: {smoke.detail}".strip(": "))
        )
        if not smoke.ok:
            return _finish("smoke")

    # [5] registration safety (collision / bindable)
    reg = check_registration_safety(source, existing_names=existing_names)
    tool_name = reg.signature.tool_name if reg.signature else None
    stages.append(StageResult("registration", reg.ok, reg.summary()))
    if not reg.ok:
        return _finish("registration", tool_name)

    return _finish(None, tool_name)
