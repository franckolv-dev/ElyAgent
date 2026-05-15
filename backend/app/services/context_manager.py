# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/context_manager.py
# @brief      Context / token management service
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Context / token management service.

Prevents silent truncation or crashes when conversations exceed the
model's context window — especially critical for Ollama models
(8K-32K) but also relevant for cloud models with very long system
prompts + memory injection.

Integration point (nodes.py)
----------------------------
Call ``fit_messages_to_context`` right before the LLM invocation,
in both the SLM path and the main LLM path of ``agent_node``.

SLM path  (line ~390 in nodes.py):
    ``response = await _slm_with_tools.ainvoke(
        [{"role": "system", "content": system}]
        + _sanitize_messages_for_mistral(messages)
    )``

LLM path  (line ~449 in nodes.py):
    ``_invoke_msgs = (
        [{"role": "system", "content": system}]
        + _sanitize_messages_for_mistral(messages)
    )``

In both cases, replace the raw message list with the output of:

    from app.services.context_manager import fit_messages_to_context
    from app.services.llm_provider import get_active_model

    fitted = fit_messages_to_context(
        messages=_sanitize_messages_for_mistral(messages),
        system_prompt=system,
        model=get_active_model(),        # or settings.slm_model for SLM
        reserve_for_response=1024,
    )
    _invoke_msgs = [{"role": "system", "content": system}] + fitted

This guarantees the prompt never exceeds the model's context window
regardless of conversation length, memory payload, or system prompt size.
"""
from __future__ import annotations

import logging
from typing import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Known context-window sizes (tokens)                                  #
# ------------------------------------------------------------------ #

_CONTEXT_WINDOWS: dict[str, int] = {
    # Ollama / local models
    "gemma4:26b": 32_768,
    "qwen2.5-coder:7b": 32_768,
    "phi4-mini": 8_192,
    "qwen2.5:7b": 32_768,
    "qwen2.5:7b-instruct": 32_768,
    # Cloud models
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
    "gemini-2.5-flash": 1_048_576,
    "gpt-4o": 128_000,
    # Catch-all — conservative so we never over-fill an unknown model.
    "_default": 8_192,
}

# Minimum number of user/assistant exchange pairs we always keep,
# even under extreme pressure.  4 pairs = 8 messages.
_MIN_KEEP_PAIRS = 4


# ------------------------------------------------------------------ #
# Token estimation                                                     #
# ------------------------------------------------------------------ #

def estimate_tokens(text: str) -> int:
    """Rough token estimate without external tokeniser.

    Heuristic: ~3.5 characters per token on average across English,
    French, and mixed content.  Slightly overestimates, which is safer
    than underestimating.
    """
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def estimate_message_tokens(message: BaseMessage | dict) -> int:
    """Estimate the token footprint of a single message.

    Accounts for both string and list-of-blocks content formats used
    by LangChain multi-modal messages.  Adds a small overhead (4 tokens)
    per message for role / framing tokens.
    """
    _OVERHEAD = 4  # role + separators

    if isinstance(message, dict):
        content = message.get("content", "") or ""
    else:
        content = message.content or ""

    if isinstance(content, list):
        # Multi-block content (text + images).  Only count text blocks;
        # images are handled natively by the model and don't eat into
        # the text-token budget in a meaningful way for our purposes.
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        content = " ".join(text_parts)

    return estimate_tokens(str(content)) + _OVERHEAD


def estimate_messages_tokens(messages: Sequence[BaseMessage | dict]) -> int:
    """Total token estimate for a list of messages."""
    return sum(estimate_message_tokens(m) for m in messages)


# ------------------------------------------------------------------ #
# Context-window lookup                                                #
# ------------------------------------------------------------------ #

def get_context_window(model: str) -> int:
    """Return the context-window size for *model*.

    Falls back to ``_default`` for unknown models.
    """
    if model in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[model]

    # Try prefix matching for versioned model names
    # (e.g. "claude-sonnet-4-6-20250514" should match "claude-sonnet-4-6").
    for key, value in _CONTEXT_WINDOWS.items():
        if key != "_default" and model.startswith(key):
            return value

    logger.debug(
        "Unknown model '%s' — using default context window (%d tokens)",
        model,
        _CONTEXT_WINDOWS["_default"],
    )
    return _CONTEXT_WINDOWS["_default"]


# ------------------------------------------------------------------ #
# Summariser for dropped messages                                      #
# ------------------------------------------------------------------ #

def _summarise_dropped(messages: Sequence[BaseMessage | dict]) -> str:
    """Build a concise recap of messages that were dropped.

    This is a *local* summary (no LLM call) to keep the operation
    synchronous and zero-cost.  It extracts the first ~120 chars of
    each user/assistant turn so the model retains a rough idea of
    what was discussed earlier.
    """
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "?")
            content = msg.get("content", "") or ""
        else:
            role = msg.type  # "human", "ai", "tool", "system"
            content = msg.content or ""

        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            )

        snippet = str(content).replace("\n", " ")[:120].strip()
        if snippet:
            lines.append(f"[{role}] {snippet}")

    if not lines:
        return ""

    return (
        "[Contexte tronque] Les messages suivants ont ete resumes pour "
        "respecter la limite de contexte du modele :\n"
        + "\n".join(lines)
    )


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

def fit_messages_to_context(
    messages: list[BaseMessage | dict],
    system_prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
    reserve_for_response: int = 1024,
) -> list[BaseMessage | dict]:
    """Trim *messages* so they fit within the model's context window.

    Parameters
    ----------
    messages:
        Conversation messages **excluding** the system prompt (which is
        counted separately).
    system_prompt:
        The system prompt that will be prepended.  Only used for token
        counting — it is **not** included in the returned list.
    model:
        Model name used to look up the context window.  Ignored when
        *max_tokens* is provided explicitly.
    max_tokens:
        Override the context window size instead of looking it up by
        model name.
    reserve_for_response:
        Number of tokens to keep free for the model's response.

    Returns
    -------
    list[BaseMessage | dict]
        Possibly shortened message list that fits within the budget.
        The system prompt is **not** part of the returned list.
    """
    if max_tokens is None:
        if model is None:
            ctx = _CONTEXT_WINDOWS["_default"]
        else:
            ctx = get_context_window(model)
    else:
        ctx = max_tokens

    budget = ctx - reserve_for_response
    system_cost = estimate_tokens(system_prompt) + 4  # +4 for role overhead

    if budget <= system_cost:
        logger.error(
            "System prompt alone (%d tokens) exceeds context budget "
            "(%d tokens after reserving %d for response in a %d-token "
            "window).  Returning last %d message pairs only.",
            system_cost, budget, reserve_for_response, ctx, _MIN_KEEP_PAIRS,
        )
        # Return at least the tail so the model has *something*.
        return messages[-(_MIN_KEEP_PAIRS * 2):]

    available = budget - system_cost
    total_cost = estimate_messages_tokens(messages)

    if total_cost <= available:
        # Everything fits — nothing to do.
        return messages

    # ── Need to truncate ──────────────────────────────────────────────
    logger.warning(
        "Context overflow: %d message tokens + %d system tokens = %d, "
        "but budget is %d tokens (model=%s, window=%d, reserve=%d). "
        "Truncating oldest messages.",
        total_cost, system_cost, total_cost + system_cost,
        budget, model or "?", ctx, reserve_for_response,
    )

    # Strategy: keep the newest messages and drop from the front.
    # We always preserve at least _MIN_KEEP_PAIRS exchanges from the
    # tail so the model has recent conversational context.

    min_keep = _MIN_KEEP_PAIRS * 2  # 2 messages per pair
    if len(messages) <= min_keep:
        # Can't drop anything further — return as-is and hope for the
        # best (the model may still truncate internally).
        logger.warning(
            "Only %d messages left — cannot truncate further.", len(messages),
        )
        return messages

    # Walk backwards from the end, accumulating token cost, until we
    # either run out of budget or include all messages.
    keep_from = len(messages)
    running = 0
    for i in range(len(messages) - 1, -1, -1):
        msg_cost = estimate_message_tokens(messages[i])
        if running + msg_cost > available:
            break
        running += msg_cost
        keep_from = i

    # Ensure we keep at least the minimum tail.
    max_keep_from = len(messages) - min_keep
    if keep_from > max_keep_from:
        keep_from = max_keep_from

    # ───────────────────────────────────────────────────────────────────
    # Tool-pair-aware trimming (bug fix, audit 2026-05-15)
    #
    # If keep_from lands on a `tool` message (ToolMessage / dict
    # {"role": "tool"}), we have a dangling tool_response whose preceding
    # tool_call assistant message just got dropped. DeepSeek and most
    # other providers reject this with:
    #     400 — "Messages with role 'tool' must be a response to a
    #     preceding message with 'tool_calls'"
    #
    # We therefore advance keep_from past any orphan tool messages until
    # we hit a real human/assistant turn. May drop a few extra messages
    # but keeps the conversation valid for ALL providers.
    # ───────────────────────────────────────────────────────────────────
    from langchain_core.messages import ToolMessage as _Tool, AIMessage as _AI

    def _is_orphan_tool(msg) -> bool:
        # langchain BaseMessage variant
        if isinstance(msg, _Tool):
            return True
        # dict variant from raw API payloads
        if isinstance(msg, dict) and msg.get("role") == "tool":
            return True
        return False

    while keep_from < len(messages) and _is_orphan_tool(messages[keep_from]):
        keep_from += 1

    # Same protection in the other direction: if the LAST kept message is
    # an assistant with tool_calls but no following tool response, that's
    # also rejected by some providers. We trim it from the tail.
    def _has_unanswered_tool_calls(msg) -> bool:
        if isinstance(msg, _AI):
            tcs = getattr(msg, "tool_calls", None) or []
            return bool(tcs)
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            return bool(msg.get("tool_calls"))
        return False

    while (
        len(messages) - keep_from > min_keep  # don't go below floor
        and _has_unanswered_tool_calls(messages[-1])
    ):
        # Trim the dangling tool_call assistant from the tail
        messages = messages[:-1]

    kept = messages[keep_from:]
    dropped = messages[:keep_from]

    if not dropped:
        return messages

    logger.info(
        "Dropped %d oldest messages (%d tokens), keeping %d messages "
        "(%d tokens).",
        len(dropped),
        estimate_messages_tokens(dropped),
        len(kept),
        estimate_messages_tokens(kept),
    )

    # Build a lightweight summary of what was dropped. It used to be
    # injected as a SystemMessage but Mistral's chat template forbids
    # consecutive system messages AND requires user→assistant alternation
    # right after the (single) system block. We therefore inject it as
    # a HumanMessage. If the kept list already starts with a HumanMessage,
    # we PREPEND the summary into that message's content instead of
    # creating a new one — same protection, no alternation violation.
    # (Audit 2026-05-07 — bug observed on ministral-3-8b-instruct.)
    summary_text = _summarise_dropped(dropped)
    if summary_text:
        summary_cost = estimate_tokens(summary_text) + 4
        if running + summary_cost <= available:
            from langchain_core.messages import HumanMessage as _HM
            preface = (
                "[Contexte résumé du début de conversation, à prendre en compte "
                "pour ta réponse]\n" + summary_text + "\n\n[Fin du résumé]\n\n"
            )
            if kept and isinstance(kept[0], _HM):
                # Merge into the first user message to keep alternation tight.
                merged_content = preface + str(kept[0].content or "")
                kept[0] = kept[0].model_copy(update={"content": merged_content})
            elif kept and isinstance(kept[0], dict) and kept[0].get("role") == "user":
                merged = preface + str(kept[0].get("content") or "")
                kept[0] = {**kept[0], "content": merged}
            else:
                # Otherwise insert a synthetic HumanMessage before whatever
                # role kept[0] has (assistant / tool / etc.). This satisfies
                # Mistral's "after system, must be user" rule.
                summary_msg: BaseMessage | dict
                if kept and isinstance(kept[0], BaseMessage):
                    summary_msg = _HM(content=preface)
                else:
                    summary_msg = {"role": "user", "content": preface}
                kept = [summary_msg] + kept
        else:
            logger.debug(
                "Summary (%d tokens) doesn't fit — skipping.", summary_cost,
            )

    return kept
