# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_loader.py
# @brief      Sprint 4b V2 J7a — tests for the safe in-process tool compiler.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app/services/learning/tool_loader.compile_tool_source``.

This is the riskiest module (it exec's generated code), so the tests pin
its two safety properties hard: (1) it never exec's un-guarded source,
(2) it never mutates the global skill registry at compile time. Plus the
happy path (a real bindable, invokable StructuredTool) and each error
stage.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning.tool_loader import (
    compile_tool_source,
    extract_register_metadata,
)


VALID = textwrap.dedent(
    '''
    from langchain_core.tools import tool

    from app.skills.base import Domain
    from app.skills.decorator import register


    @register(
        domain=Domain.WORKSPACE,
        skill_name="double_it",
        skill_display_name="Double",
        skill_description="Doubles x.",
        skill_icon="✖️",
        enabled_by_default=False,
    )
    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
)


# ── happy path ─────────────────────────────────────────────────────────────────


def test_compiles_to_invokable_bindable_tool() -> None:
    res = compile_tool_source(VALID)
    assert res.ok, res.error
    assert res.name == "double_it"
    # it is a real, invokable LangChain tool
    assert res.tool.invoke({"x": 21}) == 42
    # and it is bindable (the loader ran convert_to_openai_tool internally)
    from langchain_core.utils.function_calling import convert_to_openai_tool

    assert convert_to_openai_tool(res.tool)["function"]["name"] == "double_it"


def test_register_metadata_is_extracted() -> None:
    res = compile_tool_source(VALID)
    assert res.metadata["skill_name"] == "double_it"
    assert res.metadata["domain"] == "WORKSPACE"
    assert res.metadata["enabled_by_default"] is False


def test_extract_register_metadata_standalone() -> None:
    meta = extract_register_metadata(VALID)
    assert meta["skill_display_name"] == "Double"
    assert meta["skill_description"] == "Doubles x."


def test_explicit_tool_name_override_is_used() -> None:
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool


        @tool("custom_name")
        def f(x: int) -> int:
            """d."""
            return x
        '''
    )
    res = compile_tool_source(src)
    assert res.ok, res.error
    assert res.name == "custom_name"


# ── SAFETY PROPERTY 1: never mutate the global registry at compile time ───────


def test_compile_does_not_mutate_global_registry() -> None:
    from app.skills.registry import get_skill_registry

    before = set(get_skill_registry().all_tool_names())
    res = compile_tool_source(VALID)  # source carries @register(skill_name="double_it")
    after = set(get_skill_registry().all_tool_names())
    assert res.ok
    # the @register decorator was stripped before exec → no registration fired
    assert before == after
    assert "double_it" not in after


# ── SAFETY PROPERTY 2: never exec un-guarded source ───────────────────────────


@pytest.mark.parametrize(
    "src",
    [
        "import os\ndef f(x: int) -> int:\n    return x\n",
        "import socket\ndef f(x: int) -> int:\n    return x\n",
        "def f(x: int) -> int:\n    return ().__class__\n",
    ],
)
def test_rejects_unguarded_source_before_exec(src: str) -> None:
    res = compile_tool_source(src)
    assert not res.ok
    assert res.error_stage == "guard"


# ── error stages ───────────────────────────────────────────────────────────────


def test_no_function_is_reported() -> None:
    res = compile_tool_source("x = 1\ny = 2\n")
    assert not res.ok
    assert res.error_stage == "no_function"


def test_module_level_exec_error_is_caught() -> None:
    # passes the guard (BROKEN ref is just a Name) but raises at exec time
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool

        BROKEN = undefined_thing


        @tool
        def f(x: int) -> int:
            """d."""
            return x
        '''
    )
    res = compile_tool_source(src)
    assert not res.ok
    assert res.error_stage == "exec"
    assert "NameError" in res.error


# ── async tool loads + binds ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_tool_loads_and_invokes() -> None:
    src = textwrap.dedent(
        '''
        from langchain_core.tools import tool


        @tool
        async def triple(x: int) -> int:
            """Triple x."""
            return x * 3
        '''
    )
    res = compile_tool_source(src)
    assert res.ok, res.error
    assert res.name == "triple"
    assert await res.tool.ainvoke({"x": 7}) == 21
