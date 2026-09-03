# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_orchestrator.py
# @brief      Sprint 4b V2 J6 — tests for the validation-chain orchestrator.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for ``app/services/learning/tool_orchestrator.validate_tool_source``.

One source crafted to fail at each stage, asserting the chain fails-fast
at exactly that stage (and not before). Plus the happy path where all 5
stages pass, and the JSON serialisation of the report.
"""
from __future__ import annotations

import json
import textwrap

from app.services.learning.tool_orchestrator import validate_tool_source


VALID = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
)


def test_happy_path_all_stages_pass() -> None:
    report = validate_tool_source(
        VALID, existing_names={"gmail_list_emails"}, smoke_kwargs={"x": 21}
    )
    assert report.ok, report.summary()
    assert report.failed_stage is None
    assert report.tool_name == "double_it"
    passed = [s.stage for s in report.stages]
    assert passed == ["ast", "ruff", "mypy", "smoke", "registration"]


def test_fails_fast_at_ast_on_forbidden_import() -> None:
    src = "import os\n\n\ndef f(x: int) -> int:\n    return x\n"
    report = validate_tool_source(src, existing_names=set(), smoke_kwargs={"x": 1})
    assert not report.ok
    assert report.failed_stage == "ast"
    # nothing after ast should have run
    assert [s.stage for s in report.stages] == ["ast"]


def test_fails_at_ruff_on_undefined_name() -> None:
    # passes the AST guard (missing() is just an unknown Name) but ruff F821s it
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool


        @tool
        def f() -> int:
            """d."""
            return missing()
        '''
    )
    report = validate_tool_source(src, existing_names=set(), smoke_kwargs={})
    assert not report.ok
    assert report.failed_stage == "ruff"
    assert [s.stage for s in report.stages] == ["ast", "ruff"]


def test_fails_at_mypy_on_type_mismatch() -> None:
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool


        @tool
        def f(x: int) -> str:
            """d."""
            return x
        '''
    )
    report = validate_tool_source(src, existing_names=set(), smoke_kwargs={"x": 1})
    assert not report.ok
    assert report.failed_stage == "mypy"
    assert [s.stage for s in report.stages] == ["ast", "ruff", "mypy"]


def test_fails_at_smoke_on_runtime_error() -> None:
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool


        @tool
        def f(x: int) -> int:
            """Divide 10 by x."""
            return 10 // x
        '''
    )
    report = validate_tool_source(src, existing_names=set(), smoke_kwargs={"x": 0})
    assert not report.ok
    assert report.failed_stage == "smoke"
    assert [s.stage for s in report.stages] == ["ast", "ruff", "mypy", "smoke"]


def test_fails_at_registration_on_name_collision() -> None:
    report = validate_tool_source(
        VALID, existing_names={"double_it"}, smoke_kwargs={"x": 21}
    )
    assert not report.ok
    assert report.failed_stage == "registration"
    assert [s.stage for s in report.stages] == ["ast", "ruff", "mypy", "smoke", "registration"]


def test_run_smoke_false_skips_stage_4() -> None:
    report = validate_tool_source(
        VALID, existing_names=set(), run_smoke=False
    )
    assert report.ok
    assert [s.stage for s in report.stages] == ["ast", "ruff", "mypy", "registration"]


def test_report_serialises_to_json() -> None:
    report = validate_tool_source(VALID, existing_names=set(), smoke_kwargs={"x": 2})
    blob = report.to_json()
    data = json.loads(blob)
    assert data["ok"] is True
    assert data["tool_name"] == "double_it"
    assert {s["stage"] for s in data["stages"]} == {
        "ast", "ruff", "mypy", "smoke", "registration"
    }
