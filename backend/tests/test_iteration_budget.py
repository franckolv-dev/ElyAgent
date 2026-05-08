# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_iteration_budget.py
# @brief      Tests for iteration_count + force_summary_node (Hermes Chantier 9)
# =============================================================================
"""Tests for the iteration-budget guard.

Why
---
Heavy multi-step tasks (« audit my last 30 days of mail, group by category »)
can chain 25-50 tool calls. Without a guard, LangGraph hits its
``recursion_limit=100`` and raises a hard exception → user sees an error,
loses the whole conversation. The Chantier 9 fix counts iterations in the
agent state and routes to a ``force_summary`` terminal node when the
counter crosses ``MAX_AGENT_ITERATIONS``.

This test suite covers :
- ``should_continue`` returns ``"force_summary"`` at threshold, else routes
  ``"tools"`` / ``"end"`` as before
- ``force_summary_node`` produces a textual response without tool_calls
  even when the LLM call fails
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import (
    MAX_AGENT_ITERATIONS,
    force_summary_node,
    should_continue,
)


# ──────────────────────────────────────────────────────────────────────────────
# should_continue routing
# ──────────────────────────────────────────────────────────────────────────────


def _ai_with_tools(n: int = 1) -> AIMessage:
    """Build an AIMessage carrying ``n`` synthetic tool_calls."""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {"name": f"tool_{i}", "args": {}, "id": f"id_{i}", "type": "tool_call"}
        for i in range(n)
    ]
    return msg


def _ai_text(content: str = "Voici ma réponse.") -> AIMessage:
    """Build a plain AIMessage with text content, no tool_calls."""
    return AIMessage(content=content)


def test_should_continue_routes_to_tools_below_threshold():
    state = {"messages": [_ai_with_tools()], "iteration_count": 5}
    assert should_continue(state) == "tools"


def test_should_continue_routes_to_end_when_no_tool_calls():
    state = {"messages": [_ai_text()], "iteration_count": 5}
    assert should_continue(state) == "end"


def test_should_continue_routes_to_force_summary_at_threshold():
    """At exactly MAX_AGENT_ITERATIONS with pending tool_calls, route to force_summary."""
    state = {
        "messages": [_ai_with_tools()],
        "iteration_count": MAX_AGENT_ITERATIONS,
    }
    assert should_continue(state) == "force_summary"


def test_should_continue_routes_to_force_summary_above_threshold():
    """Even well past the threshold, the route is still force_summary."""
    state = {
        "messages": [_ai_with_tools()],
        "iteration_count": MAX_AGENT_ITERATIONS + 10,
    }
    assert should_continue(state) == "force_summary"


def test_should_continue_force_summary_only_with_pending_tool_calls():
    """If the model already produced text (no tool_calls), route to end
    even if the counter is exhausted — there's nothing left to do."""
    state = {
        "messages": [_ai_text()],
        "iteration_count": MAX_AGENT_ITERATIONS + 5,
    }
    assert should_continue(state) == "end"


def test_should_continue_default_iteration_count_is_zero():
    """Missing iteration_count in state must NOT crash the router."""
    state = {"messages": [_ai_with_tools()]}
    assert should_continue(state) == "tools"


# ──────────────────────────────────────────────────────────────────────────────
# force_summary_node
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_summary_node_returns_textual_message():
    """The node must invoke the LLM (without tools) and return its response
    wrapped as a single AIMessage in the state."""
    fake_response = AIMessage(content="Voici ce que j'ai fait : 12 mails analysés...")
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    with patch(
        "app.services.llm_provider.get_llm_for_tier",
        return_value=fake_llm,
    ):
        result = await force_summary_node({
            "messages": [
                HumanMessage(content="audite mes 30 derniers jours de mail"),
                _ai_with_tools(),
            ],
            "iteration_count": MAX_AGENT_ITERATIONS,
            "user_id": "u1",
            "conversation_id": "c1",
        })

    # Returns the response in messages
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert "12 mails analysés" in result["messages"][0].content
    # LLM was invoked exactly once (no tool loop)
    fake_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_force_summary_node_appends_forcing_user_message():
    """The forcing message instructing « no more tool_calls, summarise »
    must be appended to the prompt so the LLM sees it."""
    fake_response = AIMessage(content="Résumé...")
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    with patch(
        "app.services.llm_provider.get_llm_for_tier",
        return_value=fake_llm,
    ):
        await force_summary_node({
            "messages": [HumanMessage(content="x")],
            "iteration_count": MAX_AGENT_ITERATIONS,
            "user_id": "u1",
            "conversation_id": "c1",
        })

    sent_messages = fake_llm.ainvoke.call_args[0][0]
    # Last message should be our forcing instruction
    last = sent_messages[-1]
    last_content = last.content if hasattr(last, "content") else last.get("content", "")
    assert "limite d'itérations" in last_content
    assert "AUCUN nouvel outil" in last_content


@pytest.mark.asyncio
async def test_force_summary_node_resilient_to_llm_failure():
    """If the summary LLM call itself fails, the node must still emit a
    fallback AIMessage — never raise — so the graph terminates cleanly."""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=RuntimeError("network down"))

    with patch(
        "app.services.llm_provider.get_llm_for_tier",
        return_value=fake_llm,
    ):
        result = await force_summary_node({
            "messages": [HumanMessage(content="x")],
            "iteration_count": MAX_AGENT_ITERATIONS + 2,
            "user_id": "u1",
            "conversation_id": "c1",
        })

    assert "messages" in result
    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    # The fallback string mentions the budget so the user understands
    assert str(MAX_AGENT_ITERATIONS) in msg.content
    assert "limite" in msg.content.lower()


@pytest.mark.asyncio
async def test_force_summary_node_handles_no_user_message():
    """Edge case : if the conversation contains only AIMessages somehow,
    the node must still build a sensible prompt (default tier MEDIUM)."""
    fake_response = AIMessage(content="ok")
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    with patch(
        "app.services.llm_provider.get_llm_for_tier",
        return_value=fake_llm,
    ):
        result = await force_summary_node({
            "messages": [_ai_with_tools()],  # no HumanMessage
            "iteration_count": MAX_AGENT_ITERATIONS,
            "user_id": "u1",
            "conversation_id": "c1",
        })

    assert isinstance(result["messages"][0], AIMessage)


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────


def test_max_agent_iterations_leaves_safety_margin():
    """LangGraph recursion_limit is 100 (set in chat.py). MAX_AGENT_ITERATIONS
    must be strictly less, with margin for force_summary + tool_node + end
    nodes that still consume recursion budget."""
    assert MAX_AGENT_ITERATIONS < 100
    assert 100 - MAX_AGENT_ITERATIONS >= 10  # at least 10 cycles of headroom
