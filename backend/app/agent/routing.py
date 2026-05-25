# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/routing.py
# @brief      Sprint refactor nodes.py Phase 2.1 — LangGraph routing
#             decision + iteration budget (Hermes Chantier 9).
# @license    PolyForm Strict License 1.0.0
# @version    1.7.1
# =============================================================================
"""Iteration budget — Hermes Chantier 9.

Why
---
On heavy multi-step tasks ("audit my last 30 days of mail and group by
category"), the agent can chain 25-50 tool calls. LangGraph's
``recursion_limit=100`` (set in chat.py) caps the loop, but when it's hit
it raises a hard exception → the user sees a generic error and the
whole conversation context is lost.

Hermes solution : count loops, and at ~80 iterations FORCE a final API
call without tools, asking the model "summarise what you did so far,
don't call any more tools". This guarantees the user always receives
textual output even on overrun tasks.

Numbers
-------
- ``MAX_AGENT_ITERATIONS = 80``  → trigger force_summary
- LangGraph ``recursion_limit = 100`` (in chat.py) → safety margin of 20
  iterations to let force_summary_node + tool_node + agent_node finish
  cleanly without hitting the hard cap.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


MAX_AGENT_ITERATIONS: int = 80


def should_continue(state: AgentState) -> str:
    """Routing decision after agent_node :
    - "force_summary" if the iteration budget is exhausted (Chantier 9)
    - "tools" if the model emitted tool_calls
    - "end" otherwise (final textual answer)
    """
    last_message = state["messages"][-1]
    iter_count = state.get("iteration_count", 0)

    if (
        isinstance(last_message, AIMessage)
        and last_message.tool_calls
        and iter_count >= MAX_AGENT_ITERATIONS
    ):
        logger.warning(
            "[iteration_budget] count=%d ≥ %d — forcing final summary "
            "without tools (Chantier 9)",
            iter_count, MAX_AGENT_ITERATIONS,
        )
        return "force_summary"

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
