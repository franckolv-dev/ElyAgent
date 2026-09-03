# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/message_sanitizer.py
# @brief      Sprint refactor nodes.py Phase 1.2 — message sanitizer +
#             tool-result helper, extracted from the God Object.
# @license    MIT
# @version    1.7.1
# =============================================================================
"""Message-shaping helpers used by the LangGraph agent nodes.

Two small, pure utilities :

  - ``_sanitize_messages_for_mistral`` : fixes Mistral chat-template
    constraints (no None content, alternating user/assistant roles).
  - ``_tool_result`` : tiny shortcut to build a ToolMessage-style dict.

Both stay importable from ``app.agent.nodes`` via re-exports so external
consumers don't notice the relocation.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def _sanitize_messages_for_mistral(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Fix Mistral-specific chat-template constraints.

    Mistral's jinja chat template enforces:
      1. AIMessage content must NOT be None (HTTP 400 error code 3240).
         Other providers (Anthropic, Gemini, OpenAI) accept null/None.
      2. After the (single) system message, conversation roles must
         **alternate user → assistant → user → assistant**. Tool calls
         and tool results count as part of the assistant turn but the
         next user-or-tool-followed-by-assistant block must respect
         alternation. Two consecutive HumanMessages or two consecutive
         AIMessages crash with « roles must alternate ».
         (Audit 2026-05-07 — observed on ministral-3-8b-instruct.)

    This function is intentionally tolerant: it never drops information,
    it merges consecutive same-role messages by concatenating content
    with a blank-line separator.
    """
    # Pass 1 — fix None content
    pass1: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content is None:
            msg = msg.model_copy(update={"content": ""})
        pass1.append(msg)

    # Pass 2 — merge consecutive same-role messages (only Human/AI pairs;
    # ToolMessage and SystemMessage have their own placement rules)
    if len(pass1) <= 1:
        return pass1
    merged: list[BaseMessage] = [pass1[0]]
    for msg in pass1[1:]:
        prev = merged[-1]
        same_human = isinstance(prev, HumanMessage) and isinstance(msg, HumanMessage)
        same_ai = (
            isinstance(prev, AIMessage)
            and isinstance(msg, AIMessage)
            # Don't merge if either side carries tool_calls — that would
            # blur structured tool-use payloads with prose.
            and not getattr(prev, "tool_calls", None)
            and not getattr(msg, "tool_calls", None)
        )
        if same_human or same_ai:
            merged_content = (
                str(prev.content or "").rstrip()
                + "\n\n"
                + str(msg.content or "").lstrip()
            ).strip()
            merged[-1] = prev.model_copy(update={"content": merged_content})
        else:
            merged.append(msg)
    return merged


def _tool_result(content: str, tool_call_id: str) -> dict:
    """Build the dict shape expected by LangChain for a tool response."""
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}
