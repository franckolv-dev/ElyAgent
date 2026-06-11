# =============================================================================
# @project    ELY — Exactly Like You
# @file       tests/test_graduated_fibonacci.py
# @brief      Pin de graduation — généré avec le tool (Sprint 4d V4).
# @license    Elastic License 2.0
# =============================================================================
"""Pin du tool gradué ``fibonacci`` : importable, bindable, stable."""
from __future__ import annotations

import importlib
import json


def _load_tool():
    module = importlib.import_module("app.agent.tools.graduated.fibonacci_tool")
    tool = getattr(module, "fibonacci", None)
    assert tool is not None, "le module gradué doit exposer le tool"
    return tool


def test_fibonacci_is_a_bindable_tool():
    tool = _load_tool()
    # StructuredTool LangChain : nom stable + docstring (le LLM en dépend).
    assert tool.name == "fibonacci"
    assert (tool.description or "").strip() != ""


def test_fibonacci_module_has_provenance_header():
    import inspect
    module = importlib.import_module("app.agent.tools.graduated.fibonacci_tool")
    source = inspect.getsource(module)
    assert "PROVENANCE" in source and "@register" in source
