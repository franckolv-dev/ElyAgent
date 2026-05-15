# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_session_search.py
# @brief      Unit tests for the cross-conversation memory recall service.
#             Sprint 1, Phase 2.
#
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for session_search.py helpers.

End-to-end summarisation testing (with Ministral live) is exercised
manually via a docker-compose-exec script; the unit suite here covers
the deterministic helpers: grouping, ranking, JSON extraction, dump
truncation.
"""
from __future__ import annotations

import pytest

from app.services import session_search as ss


# ── Grouping ──────────────────────────────────────────────────────────


def test_group_by_conversation_aggregates_scores():
    """Multiple matches in the same conv are summed."""
    raw = [
        {"conversation_id": "A", "message_id": "m1", "rank": -1.0,
         "role": "user", "snippet": "x", "created_at_ts": 0},
        {"conversation_id": "A", "message_id": "m2", "rank": -0.5,
         "role": "assistant", "snippet": "x", "created_at_ts": 1},
        {"conversation_id": "B", "message_id": "m3", "rank": -2.0,
         "role": "user", "snippet": "x", "created_at_ts": 2},
    ]
    grouped = ss._group_matches_by_conversation(raw)
    # A has cumulative score 1.0 + 0.5 = 1.5, B has 2.0
    # Best score wins → B first, A second
    assert grouped[0][0] == "B"
    assert grouped[0][2] == pytest.approx(2.0)
    assert grouped[1][0] == "A"
    assert grouped[1][2] == pytest.approx(1.5)


def test_group_handles_single_match_per_conv():
    raw = [
        {"conversation_id": "A", "message_id": "m1", "rank": -1.0,
         "role": "user", "snippet": "x", "created_at_ts": 0},
    ]
    grouped = ss._group_matches_by_conversation(raw)
    assert len(grouped) == 1
    assert grouped[0][0] == "A"
    assert len(grouped[0][1]) == 1


def test_group_handles_empty_input():
    assert ss._group_matches_by_conversation([]) == []


# ── JSON extraction from LLM output ───────────────────────────────────


def test_extract_json_strict():
    """Clean JSON parses directly."""
    text = '{"title": "Foo", "summary": "Bar"}'
    result = ss._extract_json(text)
    assert result == {"title": "Foo", "summary": "Bar"}


def test_extract_json_with_markdown_fence():
    """Output wrapped in a ```json fence is unwrapped."""
    text = """```json
{"title": "Foo", "summary": "Bar"}
```"""
    result = ss._extract_json(text)
    assert result == {"title": "Foo", "summary": "Bar"}


def test_extract_json_with_bare_fence():
    """Fence without language tag also works."""
    text = """```
{"title": "Foo", "summary": "Bar"}
```"""
    result = ss._extract_json(text)
    assert result == {"title": "Foo", "summary": "Bar"}


def test_extract_json_with_preamble():
    """A short preamble before the JSON is tolerated (brace-counting fallback)."""
    text = "Voici le JSON demandé : {\"title\": \"Foo\", \"summary\": \"Bar\"}"
    result = ss._extract_json(text)
    assert result == {"title": "Foo", "summary": "Bar"}


def test_extract_json_returns_none_on_garbage():
    """Non-JSON returns None instead of raising."""
    assert ss._extract_json("This is not JSON at all") is None
    assert ss._extract_json("") is None
    assert ss._extract_json(None) is None  # type: ignore[arg-type]


def test_extract_json_returns_none_on_truncated_json():
    """Unclosed brace doesn't crash."""
    assert ss._extract_json('{"title": "Foo", "summary":') is None


# ── content normalisation (LangChain union type) ──────────────────────


def test_content_to_text_plain_string():
    assert ss._content_to_text("Hello world") == "Hello world"


def test_content_to_text_none():
    assert ss._content_to_text(None) == ""


def test_content_to_text_list_of_typed_blocks():
    """LM Studio / Anthropic-style list of blocks."""
    content = [
        {"type": "text", "text": "First part. "},
        {"type": "text", "text": "Second part."},
    ]
    assert ss._content_to_text(content) == "First part. Second part."


def test_content_to_text_list_of_mixed():
    """List with both strings and dicts."""
    content = [
        "Raw string. ",
        {"type": "text", "text": "Block. "},
        {"content": "Another field. "},
    ]
    assert ss._content_to_text(content) == "Raw string. Block. Another field. "


def test_content_to_text_single_dict():
    assert ss._content_to_text({"type": "text", "text": "Hello"}) == "Hello"
    assert ss._content_to_text({"content": "World"}) == "World"


def test_content_to_text_dict_without_text_returns_empty():
    """Dict without 'text'/'content' keys → empty string (triggers fallback).

    Acceptable behaviour: the calling summariser falls back to a snippet-
    based summary when the LLM output is unparseable, so returning ""
    here is preferable to leaking repr() noise into the JSON parser.
    """
    content = {"reasoning": "I thought about it.", "other": 42}
    result = ss._content_to_text(content)
    assert isinstance(result, str)
    assert result == ""


# ── User prompt formatting ────────────────────────────────────────────


def test_user_prompt_contains_query_and_date():
    prompt = ss._user_prompt(
        query="pompes Bestway",
        conversation_dump="[USER] hello\n[ASSISTANT] hi",
        date_str="15 mai 2026",
    )
    assert "pompes Bestway" in prompt
    assert "15 mai 2026" in prompt
    assert "[USER] hello" in prompt
    assert "[ASSISTANT] hi" in prompt
    # The instruction to respond as JSON is in the system prompt, not here
    assert "JSON" in prompt  # at least the "Résume au format JSON demandé" footer


# ── Tunable safety ─────────────────────────────────────────────────────


def test_tunables_are_sane():
    """Catches accidental edits that would make this unusable."""
    assert ss._FTS_LIMIT >= 10
    assert ss._MAX_CONTEXT_CHARS >= 10_000
    assert ss._MAX_MESSAGE_CHARS >= 500
    # Per-message cap should be much smaller than total budget so we
    # can fit many messages into one dump
    assert ss._MAX_MESSAGE_CHARS * 10 <= ss._MAX_CONTEXT_CHARS
