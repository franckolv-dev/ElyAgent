# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_h1_kill_switch.py
# @brief      Hotfix v1.11.1 — H-1 anti-hallucination kill-switch wiring guard
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Guards for the H-1 kill-switch (HALLUCINATION_GUARD_DISABLED).

The H-1 guard lives inline in ``agent_node`` (app/agent/nodes.py): when a
LOCAL model returns plain text instead of a tool_call on an action query,
it raises a synthetic ``h1_fallback`` error to force a cloud fallback.
That's the right default, but it makes benchmarking a fresh local model
painful — every tool query silently escapes to DeepSeek.

The kill-switch lets Franck disable that forced fallback during a bench
session. Because the logic is inline (no importable helper), we assert
the wiring at source level — the same pattern the project already uses
for the record_* call-site guards in test_learning_signals.py.
"""
from __future__ import annotations

import importlib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_NODES_SRC = (_REPO / "app" / "agent" / "nodes.py").read_text(encoding="utf-8")


def test_nodes_module_has_os_in_scope() -> None:
    """Regression (2026-05-31 prod outage) : the H-1 kill-switch reads
    ``os.getenv(...)`` inline in ``agent_node``, but ``import os`` was
    missing from nodes.py — every action query raised ``NameError: name
    'os' is not defined`` and the whole chat returned "erreur interne".

    The existing source-string assertions below could not catch it (they
    never import/execute the module). This one imports nodes.py and asserts
    every module-level name its ``os.`` references resolve to is actually
    bound — i.e. ``os`` is the stdlib module in the module's namespace.
    """
    import os as _stdlib_os

    nodes = importlib.import_module("app.agent.nodes")
    assert getattr(nodes, "os", None) is _stdlib_os, (
        "app.agent.nodes must `import os` — the H-1 kill-switch calls "
        "os.getenv() inline in agent_node, which NameErrors at runtime "
        "without the module-level import."
    )


def test_h1_kill_switch_env_var_is_read() -> None:
    """The H-1 block must read HALLUCINATION_GUARD_DISABLED."""
    assert "HALLUCINATION_GUARD_DISABLED" in _NODES_SRC, (
        "nodes.py must read the HALLUCINATION_GUARD_DISABLED env var so a "
        "bench session can disable the forced cloud fallback."
    )


def test_h1_kill_switch_gates_the_fallback_condition() -> None:
    """The synthetic h1_fallback must be guarded by `not _h1_disabled` so
    a truthy kill-switch actually suppresses the forced fallback."""
    assert "_h1_disabled" in _NODES_SRC
    assert "and not _h1_disabled" in _NODES_SRC, (
        "the H-1 `if` that raises h1_fallback must include `and not "
        "_h1_disabled`, otherwise the kill-switch has no effect."
    )


def test_h1_kill_switch_accepts_standard_truthy_values() -> None:
    """Consistency with the other env toggles in the codebase
    (LEARNED_SKILLS_CURATOR_DISABLED, USER_STATE_DISABLED): accept the
    1/true/yes/on family."""
    # The membership set literal must be present near the env read.
    for token in ('"1"', '"true"', '"yes"', '"on"'):
        assert token in _NODES_SRC, (
            f"H-1 kill-switch should treat {token} as truthy for "
            "consistency with the other *_DISABLED env toggles."
        )


def test_h1_synthetic_fallback_marker_still_present() -> None:
    """Regression : the kill-switch edit must NOT have removed the actual
    H-1 fallback trigger — only gated it."""
    assert "h1_fallback" in _NODES_SRC, (
        "the synthetic h1_fallback RuntimeError must still exist — the "
        "kill-switch only adds a gate, it doesn't remove the guard."
    )
