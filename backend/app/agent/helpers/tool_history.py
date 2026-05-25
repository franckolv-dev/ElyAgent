# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/tool_history.py
# @brief      Sprint refactor nodes.py Phase 1.3 — heavy-payload stripper
#             for tool results stored in the LangGraph state.
# @license    PolyForm Strict License 1.0.0
# @version    1.7.1
# =============================================================================
"""Heavy-payload stripping for tool messages.

Why
---
Several tools (``browser_screenshot``, ``browser_search_images``,
``generate_image``) return JSON whose ``data`` field carries a base64-
encoded image (often 100-300 KB → 100k-300k tokens). The frontend needs
this payload to render the image inline, but the LLM does NOT — for
chaining tool calls (``gmail_send_with_local_attachment``,
``drive_create_file``…) the model only needs ``local_path``.

Without stripping, every multi-turn workflow that includes a screenshot
saturates the model's context window. Observed 2026-05-08 :

- Qwen 2.5 14B local : 216k tokens → TruncateMiddle → model loses its own
  tool args, hallucinates paths, workflow collapses
- Qwen 3.6 Flash via DashScope : context bloat slows tour 2 by ~5×

Stripping in the tool_message that goes back into LangGraph's state
restores correct multi-turn behaviour and dramatically reduces token
cost on every provider. The frontend has already consumed the original
(full) payload via the ``on_tool_end`` stream event ; this
transformation only affects what the model sees in its conversation
history.
"""
from __future__ import annotations

import json


# Field names that may carry oversized base64 / binary payloads.
_HEAVY_FIELDS: frozenset[str] = frozenset({
    "data",          # browser_screenshot, generate_image
    "b64",           # alternate naming
    "b64_json",      # OpenAI image API
    "image_data",    # some adapters
    "binary",        # generic
    "raw",           # generic
})

# Anything below this length is left as-is even if its key looks heavy.
# 4 000 chars ≈ 1 000 tokens — small enough to keep in context if a tool
# legitimately returns a small base64 (avatar, icon, etc.).
_HEAVY_FIELD_THRESHOLD: int = 4000


def _sanitize_tool_result_for_history(content: str) -> str:
    """Strip oversized binary payloads from a tool result before it's stored
    in the LangGraph state and sent back to the LLM at the next turn.

    The frontend has already consumed the original (full) payload via the
    ``on_tool_end`` stream event ; this transformation only affects what
    the model sees in its conversation history.

    Behaviour
    ---------
    - Non-JSON strings → returned unchanged.
    - JSON dicts → fields named ``data``, ``b64``, ``b64_json``, ``image_data``,
      ``binary``, ``raw`` are replaced by ``"[stripped: N chars …]"`` if they
      exceed ``_HEAVY_FIELD_THRESHOLD`` chars.
    - Other fields (notably ``local_path``, ``mime``, ``prompt``, ``next_steps``,
      ``url``, ``title``…) are preserved verbatim — the model needs those
      to chain subsequent tool calls.
    - Malformed JSON or non-dict roots → returned unchanged (we don't try to
      be clever).
    """
    if not content or not isinstance(content, str):
        return content
    # Cheap pre-check : avoid parsing JSON if it doesn't look like a dict
    if not content.lstrip().startswith("{"):
        return content
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return content
    if not isinstance(obj, dict):
        return content

    changed = False
    for key in list(obj.keys()):
        if key in _HEAVY_FIELDS:
            val = obj[key]
            if isinstance(val, str) and len(val) > _HEAVY_FIELD_THRESHOLD:
                obj[key] = (
                    f"[stripped: {len(val)} chars — kept in frontend payload, "
                    f"not visible to the model. Use local_path or attachment_id "
                    f"to chain next tools.]"
                )
                changed = True
    if not changed:
        return content
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        # Should never happen — obj came from json.loads — but keep the
        # original on the off-chance.
        return content
