# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/qwen_no_think.py
# @brief      Disable Qwen3 thinking mode for low-latency responses
# =============================================================================
"""Qwen3 has a built-in "thinking" mode that generates a long internal monologue
before producing the actual answer (often 1-2k extra tokens). For an interactive
assistant this adds 15-40 seconds of latency per turn — unacceptable.

Per Qwen documentation, the thinking can be disabled by appending `/no_think`
to the *last user message* (system prompt directive does not work).

This module exposes :
  - `inject_no_think(messages)` : returns a copy with /no_think appended to last user msg
  - `strip_think_block(text)`   : removes any leftover <think>...</think> blocks
"""
from __future__ import annotations

import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL)


def strip_think_block(text: str) -> str:
    """Remove <think>...</think> blocks that some Qwen3 variants emit
    even when thinking is supposed to be off."""
    if not text or "<think>" not in text:
        return text
    return _THINK_RE.sub("", text).strip()


def inject_no_think(messages: list[dict[str, Any]] | list[Any]) -> list[Any]:
    """Append `/no_think` to the last user message so Qwen3 skips thinking.

    Accepts both langchain BaseMessage objects and dict-style messages.
    Returns a NEW list (does not mutate input).
    """
    if not messages:
        return list(messages)
    out = list(messages)
    # Find the last user message (dict role or BaseMessage type)
    for i in range(len(out) - 1, -1, -1):
        msg = out[i]
        is_user = False
        # dict form
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                is_user = True
        else:
            # langchain HumanMessage
            cls = type(msg).__name__
            if cls in ("HumanMessage", "Human"):
                is_user = True
            elif hasattr(msg, "type") and getattr(msg, "type", None) == "human":
                is_user = True

        if not is_user:
            continue

        # Inject the directive
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str) and "/no_think" not in content:
                out[i] = {**msg, "content": f"{content.rstrip()} /no_think"}
        else:
            content = getattr(msg, "content", "")
            if isinstance(content, str) and "/no_think" not in content:
                # Use model_copy for pydantic models (langchain v0.3+)
                if hasattr(msg, "model_copy"):
                    out[i] = msg.model_copy(update={"content": f"{content.rstrip()} /no_think"})
                else:
                    # Fallback for older versions
                    msg.content = f"{content.rstrip()} /no_think"
                    out[i] = msg
        break  # only modify the last user message

    return out
