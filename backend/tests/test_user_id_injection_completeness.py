# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_user_id_injection_completeness.py
# @brief      CI guard — ensures every tool with InjectedToolArg user_id is
#             listed in USER_ID_TOOLS so the runtime actually injects it.
#
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""CI guard for InjectedToolArg user_id completeness.

Born from the 2026-05-17 incident :

    DeepSeek v4-flash kept replying « le tool mémoire attend un user_id
    que je n'ai pas » when asked to memorize the user's Doctolib doctor
    link. Root cause : `memory_archive`, `memory_search`, `memory_recent`
    all had `user_id: Annotated[str, InjectedToolArg]` in their
    signature, but were NOT listed in `USER_ID_TOOLS` (the frozenset
    that drives runtime injection in `nodes.py:1863`). So the LLM saw
    `user_id` as a normal parameter to fill — and honestly said it
    couldn't fill it. Same bug class as `search_past_conversations_tool`
    that we'd already had to fix once.

This test scans every tool registered in the global SkillRegistry, looks
at its signature, and fails if any tool has `InjectedToolArg user_id`
without being listed in `USER_ID_TOOLS`. Catches the next forgetting.

Run with :
    cd backend && .venv/bin/python -m pytest tests/test_user_id_injection_completeness.py -v
"""
from __future__ import annotations

import inspect
import typing

import pytest

from langchain_core.tools import InjectedToolArg


@pytest.fixture(scope="module", autouse=True)
def _register_builtins():
    """Make sure all builtin tools are registered before scanning."""
    from app.skills.builtin import register_all
    register_all()
    yield


def _has_injected_user_id(tool) -> bool:
    """Return True if the tool's function signature declares
    ``user_id`` with the ``InjectedToolArg`` annotation marker.

    LangChain @tool wraps the original function but keeps it accessible
    via `.func` (sync) or `.coroutine` (async). We try both.
    """
    func = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    if func is None:
        return False
    try:
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception:
        return False
    if "user_id" not in hints:
        return False
    hint = hints["user_id"]
    # Annotated[X, InjectedToolArg, ...] → look at the metadata
    metadata = getattr(hint, "__metadata__", ())
    for m in metadata:
        # InjectedToolArg can be the class itself or an instance
        if m is InjectedToolArg or isinstance(m, InjectedToolArg):
            return True
    return False


def test_every_injected_user_id_tool_is_in_USER_ID_TOOLS():
    """Every tool whose signature requests user_id injection MUST be
    declared in tool_sets.USER_ID_TOOLS — otherwise the runtime won't
    actually inject the value and the LLM will see user_id as a normal
    parameter to fill (and either invent one or refuse the call).
    """
    from app.agent.tool_sets import USER_ID_TOOLS
    from app.skills import get_skill_registry

    missing: list[str] = []
    for tool in get_skill_registry().all_tools:
        if _has_injected_user_id(tool) and tool.name not in USER_ID_TOOLS:
            missing.append(tool.name)

    assert not missing, (
        f"The following tools declare `user_id: InjectedToolArg` in their "
        f"signature but are NOT listed in tool_sets.USER_ID_TOOLS, so the "
        f"runtime won't inject the value: {sorted(missing)}. "
        f"Add them to USER_ID_TOOLS in backend/app/agent/tool_sets.py."
    )


def test_USER_ID_TOOLS_has_no_phantom_entries():
    """Reciprocal sanity check : every name in USER_ID_TOOLS should
    correspond to a tool that actually exists in the registry. Catches
    typos and renames that weren't propagated."""
    from app.agent.tool_sets import USER_ID_TOOLS
    from app.skills import get_skill_registry
    from app.skills.builtin.mcp_model_skill import MCP_MODEL_TOOL_NAMES

    registered = {t.name for t in get_skill_registry().all_tools}
    # Les outils model-facing du client MCP ne sont enregistrés que si le flag
    # mcp_client_v2_enabled est ON (zéro coût de contexte quand OFF). Ils sont
    # bien réels — on les exclut du contrôle anti-typo conditionnel.
    phantoms = sorted(
        name for name in USER_ID_TOOLS
        if name not in registered and name not in MCP_MODEL_TOOL_NAMES
    )

    # We allow a small number of intentional aliases (legacy tool names
    # that may not be registered today but are kept for backward compat).
    # Hard-fail only if we get a flood (>5) which would indicate drift.
    assert len(phantoms) <= 5, (
        f"USER_ID_TOOLS contains {len(phantoms)} names that are not "
        f"registered tools: {phantoms[:10]}. Either remove them from "
        f"USER_ID_TOOLS or register the corresponding tool."
    )
