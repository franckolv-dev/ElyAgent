# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_deepseek_thinking_swap.py
# @brief      Tests for the DeepSeek thinking-mode workaround
# =============================================================================
"""Tests for the DeepSeek thinking-mode disable helpers.

DeepSeek v4-flash / v4-pro have thinking mode on by default. With
tool_calls, the API requires the assistant's `reasoning_content` to
be replayed verbatim on every subsequent turn — LangChain doesn't
preserve it, so multi-turn tool_calls fail on turn 2 with HTTP 400.

Per https://api-docs.deepseek.com/guides/thinking_mode the official
disable mechanism is :

    extra_body={"thinking": {"type": "disabled"}}

These tests lock the helper behaviour against regression. Real-world
incident (mai 2026): Franck observed DeepSeek 200 OK on turn 1,
400 BadRequest on turn 2 → fallback chain switched to Ministral 14B
for the rest of the conversation.
"""
from __future__ import annotations

from app.services.llm_provider import (
    _deepseek_disable_thinking,
    _deepseek_extra_body,
)


# ── Identifiers where thinking must be disabled ─────────────────────────────


def test_v4_flash_needs_disable():
    assert _deepseek_disable_thinking("deepseek-v4-flash") is True


def test_v4_pro_needs_disable():
    assert _deepseek_disable_thinking("deepseek-v4-pro") is True


def test_v4_flash_extra_body_shape():
    body = _deepseek_extra_body("deepseek-v4-flash")
    assert body == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_v4_pro_extra_body_shape():
    body = _deepseek_extra_body("deepseek-v4-pro")
    assert body == {"extra_body": {"thinking": {"type": "disabled"}}}


# ── Identifiers that must be left alone ─────────────────────────────────────


def test_deepseek_chat_no_override():
    """deepseek-chat is already non-thinking — passing the disable param
    is harmless but unnecessary, so we skip it to keep payloads clean."""
    assert _deepseek_disable_thinking("deepseek-chat") is False
    assert _deepseek_extra_body("deepseek-chat") == {}


def test_deepseek_reasoner_no_override():
    """The user picked the reasoner explicitly — they want thinking. We
    don't override their choice; multi-turn limitations are on them."""
    assert _deepseek_disable_thinking("deepseek-reasoner") is False
    assert _deepseek_extra_body("deepseek-reasoner") == {}


def test_unknown_model_no_override():
    """Future or custom model identifiers we don't know about must not
    be touched — better to surface a real DeepSeek error than to inject
    params blindly."""
    assert _deepseek_disable_thinking("deepseek-coder-v3") is False
    assert _deepseek_extra_body("deepseek-coder-v3") == {}


def test_empty_string_no_override():
    assert _deepseek_disable_thinking("") is False
    assert _deepseek_extra_body("") == {}


# ── Case sensitivity ────────────────────────────────────────────────────────


def test_uppercase_variant_no_override():
    """The DeepSeek API is case-sensitive on model names. We match
    exactly the lowercase canonical identifiers — anything else passes
    through untouched."""
    assert _deepseek_disable_thinking("DeepSeek-V4-Flash") is False
    assert _deepseek_extra_body("DeepSeek-V4-Flash") == {}


# ── Integration: extra_body return value can be **-spread into ChatOpenAI ──


def test_extra_body_is_spreadable():
    """The helper is meant to be used as `**_deepseek_extra_body(model)`
    in a ChatOpenAI(...) call. Verify both the empty and non-empty cases
    spread cleanly into a kwargs dict."""
    base_kwargs = {"model": "deepseek-v4-flash", "api_key": "x"}
    merged = {**base_kwargs, **_deepseek_extra_body("deepseek-v4-flash")}
    assert merged["model"] == "deepseek-v4-flash"
    assert merged["api_key"] == "x"
    assert merged["extra_body"] == {"thinking": {"type": "disabled"}}

    # And the no-op case must not introduce stray keys
    merged_chat = {**base_kwargs, **_deepseek_extra_body("deepseek-chat")}
    assert merged_chat == base_kwargs
