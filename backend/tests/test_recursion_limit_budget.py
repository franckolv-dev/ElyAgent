# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_recursion_limit_budget.py
# @brief      Hotfix 2026-06-01 — the chat recursion_limit must stay above
#             2× MAX_AGENT_ITERATIONS so force_summary is reachable before
#             LangGraph raises GraphRecursionError.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Guard the iteration-budget ↔ recursion-limit unit relationship.

Incident : a long web-research loop hit the hardcoded recursion_limit=100
at ~iteration 50 and crashed with « Une erreur interne est survenue »,
because MAX_AGENT_ITERATIONS=80 is counted in tool-calling *iterations*
(≈ 2 graph super-steps each) while recursion_limit counts *super-steps*.
The force_summary safety net at iteration 80 (~160 steps) was unreachable
under a 100-step cap. The fix derives the cap from MAX_AGENT_ITERATIONS.
"""
from __future__ import annotations

from pathlib import Path


def test_recursion_limit_exceeds_double_iterations() -> None:
    """One iteration = agent_node + tool_node = 2 super-steps, so the hard
    cap must exceed 2× MAX_AGENT_ITERATIONS for force_summary to fire
    first."""
    from app.agent.routing import CHAT_RECURSION_LIMIT, MAX_AGENT_ITERATIONS

    assert CHAT_RECURSION_LIMIT > MAX_AGENT_ITERATIONS * 2, (
        f"recursion_limit ({CHAT_RECURSION_LIMIT}) must exceed "
        f"2×MAX_AGENT_ITERATIONS ({MAX_AGENT_ITERATIONS * 2}) so force_summary "
        "fires before GraphRecursionError."
    )


def test_chat_uses_derived_recursion_limit() -> None:
    """chat.py must reference the derived constant, not re-hardcode a number
    that can silently drift below the budget again."""
    src = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "chat.py"
    ).read_text(encoding="utf-8")
    assert "CHAT_RECURSION_LIMIT" in src, "chat.py must use the derived limit"
    assert '"recursion_limit": 100' not in src, (
        "the old hardcoded recursion_limit=100 must be gone — it tripped "
        "before force_summary could fire."
    )
