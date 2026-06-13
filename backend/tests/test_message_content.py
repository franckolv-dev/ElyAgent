# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_message_content.py
# @brief      content_to_text() — aplatissement du content LangChain en texte,
#             pin du crash missions « binding parameter: type 'list' » (codex).
# @license    Elastic License 2.0
# =============================================================================
"""Pins du helper partagé ``agent.helpers.message_content.content_to_text``.

Run with:  cd backend && python -m pytest tests/test_message_content.py -v
"""
from __future__ import annotations

import json

import pytest

from app.agent.helpers.message_content import content_to_text


class TestContentToText:
    def test_plain_string(self):
        assert content_to_text("Hello world") == "Hello world"

    def test_none(self):
        assert content_to_text(None) == ""

    def test_list_of_typed_blocks(self):
        content = [
            {"type": "text", "text": "First part. "},
            {"type": "text", "text": "Second part."},
        ]
        assert content_to_text(content) == "First part. Second part."

    def test_list_mixed_str_and_dict(self):
        content = ["Raw string. ", {"type": "text", "text": "Block. "},
                   {"content": "Another field. "}]
        assert content_to_text(content) == "Raw string. Block. Another field. "

    def test_single_dict(self):
        assert content_to_text({"type": "text", "text": "Hello"}) == "Hello"
        assert content_to_text({"content": "World"}) == "World"

    def test_dict_without_text_returns_empty(self):
        assert content_to_text({"reasoning": "x", "other": 42}) == ""

    def test_openai_codex_responses_shape(self):
        # Forme exacte renvoyée par openai-codex (Responses API, v0) :
        # un bloc texte avec un champ `index` en plus — c'est CE shape qui a
        # fait planter les missions (juin 2026).
        content = [{"type": "text", "text": '{"steps": []}', "index": 0}]
        assert content_to_text(content) == '{"steps": []}'

    def test_codex_reasoning_block_is_skipped(self):
        # output_version="v0" peut émettre un bloc reasoning sans texte
        # exploitable avant le bloc texte : on ne garde que le texte.
        content = [
            {"type": "reasoning", "summary": [], "content": []},
            {"type": "text", "text": "Réponse finale.", "index": 1},
        ]
        assert content_to_text(content) == "Réponse finale."


class TestRegressionMissionCrash:
    """Pin du double symptôme du bug missions sur tier codex (juin 2026)."""

    def test_list_content_yields_sliceable_string_not_list(self):
        # Symptôme 2 (crash dur) : `thought = raw[:2000]` doit donner une
        # STRING. Avant le fix, raw était une liste → raw[:2000] = liste
        # tronquée → « Error binding parameter: type 'list' is not supported ».
        codex_content = [{"type": "text", "text": "x" * 5000, "index": 0}]
        raw = content_to_text(codex_content)
        assert isinstance(raw, str)
        assert isinstance(raw[:2000], str)
        assert len(raw[:2000]) == 2000

    def test_list_content_is_json_parseable_after_flatten(self):
        # Symptôme 1 (parse cassé) : json.loads(raw.strip()) doit marcher.
        # Avant le fix, raw.strip() → « 'list' object has no attribute strip ».
        codex_content = [{"type": "text", "text": '{"steps": [{"id": "1"}]}', "index": 0}]
        raw = content_to_text(codex_content)
        parsed = json.loads(raw.strip())
        assert parsed["steps"][0]["id"] == "1"


class TestSessionSearchDelegation:
    """session_search._content_to_text doit rester un alias fidèle."""

    @pytest.mark.parametrize("value,expected", [
        ("plain", "plain"),
        (None, ""),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        ({"reasoning": "x"}, ""),
    ])
    def test_delegates_to_shared_helper(self, value, expected):
        from app.services.session_search import _content_to_text
        assert _content_to_text(value) == content_to_text(value) == expected
