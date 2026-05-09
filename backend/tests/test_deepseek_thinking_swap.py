# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_deepseek_thinking_swap.py
# @brief      Tests for the DeepSeek thinking-mode workaround
# =============================================================================
"""Tests for ``_deepseek_safe_model``.

DeepSeek v4-flash / v4-pro have thinking mode on by default. Their
response includes a `reasoning_content` field that the API requires us
to send back on every subsequent request — LangChain doesn't preserve
this state, so any multi-turn workflow with tool_calls fails on turn 2
with HTTP 400.

Workaround: transparently swap the thinking-mode aliases to
`deepseek-chat`, which DeepSeek itself documents as « v4-flash in
non-thinking mode ». These tests lock the swap behaviour against
regression — losing it would silently re-introduce the multi-turn bug.

Real-world incident (mai 2026): Franck observed DeepSeek 200 OK on
turn 1, 400 BadRequest on turn 2 → fallback chain switched to
Ministral 14B for the rest of the conversation. Investigation
pinpointed the thinking-mode handshake; this swap is the fix.
"""
from __future__ import annotations

import logging

import pytest

from app.services.llm_provider import _deepseek_safe_model


# ── Thinking-mode aliases must be swapped ────────────────────────────────────


def test_v4_flash_swapped_to_chat():
    assert _deepseek_safe_model("deepseek-v4-flash") == "deepseek-chat"


def test_v4_pro_swapped_to_chat():
    assert _deepseek_safe_model("deepseek-v4-pro") == "deepseek-chat"


def test_swap_is_logged_at_info_level(caplog):
    """The substitution emits a log line so the operator can correlate it
    with the UI settings — important when « v4-flash » in the dropdown
    silently runs as « chat »."""
    with caplog.at_level(logging.INFO, logger="app.services.llm_provider"):
        _deepseek_safe_model("deepseek-v4-flash")
    assert any(
        "deepseek-v4-flash" in r.message and "deepseek-chat" in r.message
        for r in caplog.records
    )


# ── Non-thinking identifiers pass through unchanged ─────────────────────────


def test_deepseek_chat_unchanged():
    assert _deepseek_safe_model("deepseek-chat") == "deepseek-chat"


def test_deepseek_reasoner_unchanged():
    """The user picked the reasoner explicitly — they want thinking. We
    don't override their choice; multi-turn limitations are on them."""
    assert _deepseek_safe_model("deepseek-reasoner") == "deepseek-reasoner"


def test_custom_model_id_unchanged():
    """Future or custom model identifiers we don't know about must not
    be silently rewritten — better to surface a real API error than to
    swap blindly to deepseek-chat."""
    assert _deepseek_safe_model("deepseek-coder-v3") == "deepseek-coder-v3"


def test_empty_string_unchanged():
    assert _deepseek_safe_model("") == ""


# ── Case sensitivity ────────────────────────────────────────────────────────


def test_uppercase_variant_not_swapped():
    """The DeepSeek API is case-sensitive on model names. We match
    exactly the lowercase canonical identifiers — anything else passes
    through untouched."""
    # If someone manually types "DeepSeek-V4-Flash" we don't second-guess.
    assert _deepseek_safe_model("DeepSeek-V4-Flash") == "DeepSeek-V4-Flash"
