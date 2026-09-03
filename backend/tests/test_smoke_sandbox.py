# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_smoke_sandbox.py
# @brief      Sprint 4b V2 J4 — tests for the smoke-execution sandbox.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for ``app/services/learning/smoke_sandbox.py``.

Covers the outcome taxonomy: returned / raised / nonserializable /
timeout / crashed, plus tool-function detection and async tools. The
resource-limit paths (timeout via wall-clock, CPU via RLIMIT_CPU) are
exercised with small limits to stay fast; the memory path is Linux-only
(RLIMIT_AS is not reliably enforced on macOS).
"""
from __future__ import annotations

import sys
import textwrap

import pytest

from app.services.learning.smoke_sandbox import (
    SmokeReport,
    detect_tool_func,
    smoke_run,
)


# ── detection ─────────────────────────────────────────────────────────────────


def test_detect_decorated_function() -> None:
    src = "from langchain_core.tools import tool\n\n\n@tool\ndef my_tool(x):\n    return x\n"
    assert detect_tool_func(src) == "my_tool"


def test_detect_single_undecorated_function() -> None:
    assert detect_tool_func("def only(a):\n    return a\n") == "only"


def test_detect_none_when_multiple_undecorated() -> None:
    src = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    assert detect_tool_func(src) is None


def test_detect_none_on_syntax_error() -> None:
    assert detect_tool_func("def broken(:\n    pass\n") is None


# ── happy path ─────────────────────────────────────────────────────────────────


def test_returns_serializable_value() -> None:
    report = smoke_run("def add(a, b):\n    return a + b\n", kwargs={"a": 2, "b": 3})
    assert report.ok
    assert report.outcome == "returned"
    assert report.result_repr == "5"


def test_kwargs_are_passed() -> None:
    report = smoke_run("def greet(name):\n    return 'hi ' + name\n", kwargs={"name": "ada"})
    assert report.ok
    assert report.result_repr == "'hi ada'"


def test_async_tool_is_awaited() -> None:
    src = "async def f(x):\n    return x * 2\n"
    report = smoke_run(src, kwargs={"x": 21})
    assert report.ok
    assert report.result_repr == "42"


def test_decorated_composed_tool_runs() -> None:
    src = textwrap.dedent(
        r'''
        from __future__ import annotations

        import re
        from typing import Annotated

        from langchain_core.tools import InjectedToolArg, tool

        from app.skills.base import Domain
        from app.skills.decorator import register


        @register(
            domain=Domain.WORKSPACE,
            skill_name="invoice_digest",
            skill_display_name="Invoice digest",
            skill_description="Extract an invoice number.",
            skill_icon="🧾",
            enabled_by_default=False,
        )
        @tool
        async def invoice_digest(
            text: str,
            user_id: Annotated[str, InjectedToolArg] = "",
        ) -> str:
            """Return the invoice number found in text."""
            m = re.search(r"INV-(\d+)", text)
            return m.group(1) if m else "none"
        '''
    )
    assert detect_tool_func(src) == "invoice_digest"
    report = smoke_run(src, kwargs={"text": "see INV-42 attached"})
    assert report.ok, report.detail
    assert report.result_repr == "'42'"


# ── failure outcomes ───────────────────────────────────────────────────────────


def test_raised_exception_is_reported() -> None:
    report = smoke_run("def f():\n    raise ValueError('boom')\n")
    assert not report.ok
    assert report.outcome == "raised"
    assert "ValueError" in report.detail


def test_nonserializable_result_is_rejected() -> None:
    report = smoke_run("def f():\n    return object()\n")
    assert not report.ok
    assert report.outcome == "nonserializable"


def test_no_function_found_is_error() -> None:
    report = smoke_run("x = 1\ny = 2\n")
    assert not report.ok
    assert report.outcome == "error"


# ── resource limits ────────────────────────────────────────────────────────────


def test_wall_clock_timeout() -> None:
    # sleep consumes ~no CPU → the wall-clock guard fires before RLIMIT_CPU.
    report = smoke_run(
        "import time\ndef f():\n    time.sleep(30)\n",
        cpu_seconds=20,
        timeout_s=1.0,
    )
    assert not report.ok
    assert report.outcome == "timeout"


def test_cpu_limit_kills_busy_loop() -> None:
    # a hot loop burns CPU → RLIMIT_CPU (SIGXCPU) fires before wall-clock.
    report = smoke_run(
        "def f():\n    x = 0\n    while True:\n        x += 1\n",
        cpu_seconds=1,
        timeout_s=15.0,
    )
    assert not report.ok
    assert report.outcome == "crashed"


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="RLIMIT_AS is not reliably enforced on macOS; validated on Linux CI",
)
def test_memory_limit_blocks_runaway_allocation() -> None:
    report = smoke_run(
        "def f():\n    blob = bytearray(400 * 1024 * 1024)\n    return len(blob)\n",
        mem_mb=128,
        cpu_seconds=10,
        timeout_s=15.0,
    )
    assert not report.ok
    assert report.outcome in {"raised", "crashed"}, report.detail


# ── report shape ───────────────────────────────────────────────────────────────


def test_report_carries_duration() -> None:
    report = smoke_run("def f():\n    return 1\n")
    assert isinstance(report, SmokeReport)
    assert report.duration_ms >= 0
