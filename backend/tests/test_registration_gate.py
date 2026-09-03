# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_registration_gate.py
# @brief      Sprint 4b V2 J5 — tests for the registration-safety gate.
# @license    MIT
# =============================================================================
"""Tests for ``app/services/learning/registration_gate.py``.

The gate is a static pre-filter for the real registration risks: name
collision (shadows an existing tool), bind failure (untyped signature),
unusable tool (no docstring). It must NOT mutate the registry — these
tests only feed it source + a name set.
"""
from __future__ import annotations

import textwrap

from app.services.learning.registration_gate import (
    check_registration_safety,
    extract_tool_signature,
)


VALID_TOOL = textwrap.dedent(
    '''
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
        m = re.search(r"INV-(\\d+)", text)
        return m.group(1) if m else "none"
    '''
)


def _codes(source: str, existing: set[str]) -> set[str]:
    return {i.code for i in check_registration_safety(source, existing_names=existing).issues}


# ── signature extraction ──────────────────────────────────────────────────────


def test_extract_signature_of_valid_tool() -> None:
    sig = extract_tool_signature(VALID_TOOL)
    assert sig is not None
    assert sig.func_name == "invoice_digest"
    assert sig.tool_name == "invoice_digest"
    assert sig.is_async is True
    assert sig.has_docstring is True
    assert sig.has_tool_decorator is True
    by_name = {p.name: p for p in sig.params}
    assert by_name["text"].annotated and not by_name["text"].injected
    assert by_name["user_id"].injected and by_name["user_id"].has_default


def test_extract_explicit_tool_name_override() -> None:
    src = 'from langchain_core.tools import tool\n\n\n@tool("custom_name")\ndef f(x: int) -> int:\n    """d."""\n    return x\n'
    sig = extract_tool_signature(src)
    assert sig is not None
    assert sig.func_name == "f"
    assert sig.tool_name == "custom_name"


def test_extract_none_on_syntax_error() -> None:
    assert extract_tool_signature("def broken(:\n    pass\n") is None


def test_extract_none_when_ambiguous_multiple_undecorated() -> None:
    assert extract_tool_signature("def a():\n    return 1\n\n\ndef b():\n    return 2\n") is None


# ── happy path ─────────────────────────────────────────────────────────────────


def test_valid_tool_passes_when_name_free() -> None:
    report = check_registration_safety(
        VALID_TOOL, existing_names={"gmail_list_emails", "drive_read_file"}
    )
    assert report.ok, report.summary()
    assert report.signature is not None


# ── failure cases ──────────────────────────────────────────────────────────────


def test_name_collision_detected() -> None:
    codes = _codes(VALID_TOOL, {"invoice_digest"})
    assert "name_collision" in codes


def test_collision_uses_tool_name_override() -> None:
    src = 'from langchain_core.tools import tool\n\n\n@tool("taken")\ndef f(x: int) -> int:\n    """d."""\n    return x\n'
    assert "name_collision" in _codes(src, {"taken"})
    # the function name itself does NOT collide — only the override does
    assert "name_collision" not in _codes(src, {"f"})


def test_missing_docstring_detected() -> None:
    src = "from langchain_core.tools import tool\n\n\n@tool\ndef f(x: int) -> int:\n    return x\n"
    assert "missing_docstring" in _codes(src, set())


def test_unannotated_param_detected() -> None:
    src = 'from langchain_core.tools import tool\n\n\n@tool\ndef f(x) -> int:\n    """d."""\n    return 1\n'
    assert "unannotated_param" in _codes(src, set())


def test_injected_annotated_param_not_flagged_unannotated() -> None:
    # user_id is Annotated → annotated → must NOT trip unannotated_param
    assert "unannotated_param" not in _codes(VALID_TOOL, set())


def test_missing_tool_decorator_detected() -> None:
    src = 'def f(x: int) -> int:\n    """d."""\n    return x\n'
    assert "missing_tool_decorator" in _codes(src, set())


def test_no_tool_function_detected() -> None:
    assert "no_tool_function" in _codes("x = 1\ny = 2\n", set())


def test_multiple_issues_collected() -> None:
    # collides + no docstring + unannotated param, all at once
    src = 'from langchain_core.tools import tool\n\n\n@tool\ndef dup(x):\n    return x\n'
    report = check_registration_safety(src, existing_names={"dup"})
    assert not report.ok
    codes = {i.code for i in report.issues}
    assert {"name_collision", "missing_docstring", "unannotated_param"} <= codes
