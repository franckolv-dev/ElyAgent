# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_static_checks.py
# @brief      Sprint 4b V2 J3 — tests for the ruff + mypy pipeline stages.
# @license    MIT
# =============================================================================
"""Tests for ``app/services/learning/static_checks.py``.

Covers: ruff catches undefined names (F821) + unused imports (F401) and
passes clean code; mypy catches type errors and is lenient on
missing-stub imports (langchain/app); the combined runner merges both
and reports availability. ruff + mypy are declared runtime deps, so
``available`` must be True here (a False would mean the prod image is
missing a checker the pipeline needs).
"""
from __future__ import annotations

import textwrap

from app.services.learning.static_checks import (
    _ruff_exe,
    run_mypy,
    run_ruff,
    run_static_checks,
)


# ── ruff ──────────────────────────────────────────────────────────────────────


def test_ruff_executable_is_resolvable() -> None:
    assert _ruff_exe() is not None, "ruff must be installed as a runtime dep"


def test_ruff_catches_undefined_name() -> None:
    report = run_ruff("def f() -> int:\n    return undefined_thing()\n")
    assert report.available
    assert not report.ok
    assert any(f.code == "F821" for f in report.findings), report.summary()


def test_ruff_catches_unused_import() -> None:
    report = run_ruff("import math\n\n\ndef f() -> int:\n    return 1\n")
    assert not report.ok
    assert any(f.code == "F401" for f in report.findings), report.summary()


def test_ruff_passes_clean_code() -> None:
    src = "import math\n\n\ndef f(x: float) -> float:\n    return math.sqrt(x)\n"
    report = run_ruff(src)
    assert report.ok, report.summary()


def test_ruff_finding_carries_location() -> None:
    report = run_ruff("def f() -> int:\n    return undefined_thing()\n")
    f = next(v for v in report.findings if v.code == "F821")
    assert f.tool == "ruff"
    assert f.lineno == 2


# ── mypy ────────────────────────────────────────────────────────────────────


def test_mypy_catches_return_type_mismatch() -> None:
    report = run_mypy("def f(x: int) -> str:\n    return x\n")
    assert report.available
    assert not report.ok
    assert any(f.code == "return-value" for f in report.findings), report.summary()


def test_mypy_passes_well_typed_code() -> None:
    report = run_mypy("def f(x: str) -> str:\n    return x.upper()\n")
    assert report.ok, report.summary()


def test_mypy_is_lenient_on_missing_stub_imports() -> None:
    """A generated tool imports langchain/app modules that have no stubs
    in the checking context. mypy must not fail on those — we type-check
    the tool's own logic, not the import graph (--ignore-missing-imports
    + --follow-imports=skip)."""
    src = textwrap.dedent(
        """
        from langchain_core.tools import tool


        @tool
        def f(x: str) -> str:
            return x.upper()
        """
    )
    report = run_mypy(src)
    assert report.available
    assert report.ok, report.summary()


# ── combined ─────────────────────────────────────────────────────────────────


VALID_TOOL = textwrap.dedent(
    '''
    from __future__ import annotations

    import re

    from langchain_core.tools import tool


    @tool
    def extract_digits(text: str) -> str:
        """Return the first run of digits in text, or empty string."""
        m = re.search(r"\\d+", text)
        return m.group(0) if m else ""
    '''
)

BAD_TOOL = textwrap.dedent(
    """
    import os


    def f(x: int) -> str:
        return x
    """
)


def test_run_static_checks_passes_valid_tool() -> None:
    report = run_static_checks(VALID_TOOL)
    assert report.available
    assert report.ok, report.summary()


def test_run_static_checks_fails_bad_tool() -> None:
    report = run_static_checks(BAD_TOOL)
    assert report.available
    assert not report.ok
    tools = {f.tool for f in report.findings}
    # ruff flags the unused `os`, mypy flags the bad return type
    assert "ruff" in tools and "mypy" in tools, report.summary()
