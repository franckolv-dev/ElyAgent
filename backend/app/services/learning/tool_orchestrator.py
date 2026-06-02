# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_orchestrator.py
# @brief      Sprint 4b V2 J6 — validation-chain orchestrator: runs the 5
#             pipeline stages over a generated @tool source, fail-fast.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
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

import json
from dataclasses import dataclass, field

from app.services.learning.code_guard import check_tool_source
from app.services.learning.registration_gate import check_registration_safety
from app.services.learning.smoke_sandbox import smoke_run
from app.services.learning.static_checks import run_mypy, run_ruff


# ── Report types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageResult:
    stage: str  # ast | ruff | mypy | smoke | registration
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


def validate_tool_source(
    source: str,
    *,
    existing_names: set[str] | frozenset[str],
    smoke_kwargs: dict | None = None,
    run_smoke: bool = True,
) -> ToolValidationReport:
    """Run the 5-stage validation chain over ``source``, fail-fast.

    Returns a :class:`ToolValidationReport`. The chain stops at the first
    failing stage; later stages are not run (and not listed). ``run_smoke``
    can be False when no sample input is available for stage 4.
    """
    stages: list[StageResult] = []

    def _finish(failed: str | None, tool_name: str | None = None) -> ToolValidationReport:
        return ToolValidationReport(
            ok=failed is None,
            failed_stage=failed,
            tool_name=tool_name,
            stages=tuple(stages),
        )

    # [1] AST allow-list (security) — MUST be first.
    guard = check_tool_source(source)
    stages.append(StageResult("ast", guard.ok, guard.summary()))
    if not guard.ok:
        return _finish("ast")

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
    if run_smoke:
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
