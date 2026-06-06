# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_generator.py
# @brief      Sprint 4b V2 J6 — tests for the tier-S @tool generator.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app/services/learning/tool_generator.py``.

The tier-S call is mocked (no API key, no cost) following the
skill_creator test pattern. Covers response parsing, prompt composition,
the generate_tool_source status paths, and an end-to-end check that a
generated tool passes the validation chain.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning import tool_generator
from app.services.learning.tool_generator import (
    compose_user_prompt,
    generate_tool_source,
    parse_tool_response,
)
from app.services.learning.tool_orchestrator import validate_tool_source


GENERATED_TOOL = textwrap.dedent(
    '''
    from langchain_core.tools import tool


    @tool
    def double_it(x: int) -> int:
        """Double the integer x."""
        return x * 2
    '''
).strip()


# ── parse_tool_response ────────────────────────────────────────────────────────


def test_parse_python_fenced_block() -> None:
    raw = f"Here you go:\n```python\n{GENERATED_TOOL}\n```\nHope it helps!"
    assert parse_tool_response(raw).strip() == GENERATED_TOOL


def test_parse_bare_fenced_block() -> None:
    raw = f"```\n{GENERATED_TOOL}\n```"
    assert parse_tool_response(raw).strip() == GENERATED_TOOL


def test_parse_no_fence_but_looks_like_source() -> None:
    assert parse_tool_response(GENERATED_TOOL).strip() == GENERATED_TOOL


def test_parse_returns_none_on_prose() -> None:
    assert parse_tool_response("I cannot help with that request.") is None


def test_parse_returns_none_on_empty() -> None:
    assert parse_tool_response("") is None


# ── compose_user_prompt ────────────────────────────────────────────────────────


def test_prompt_includes_task_and_tools() -> None:
    p = compose_user_prompt("merge two drive folders", available_tools=["drive_list_files"])
    assert "merge two drive folders" in p
    assert "drive_list_files" in p
    assert "AVAILABLE TOOLS" in p


# ── composition convention (PR-B) ───────────────────────────────────────────────


def test_system_prompt_teaches_call_tool_convention() -> None:
    """The generator must know the EXACT composition mechanism, else it can't
    produce a working composition tool (it would invent a calling pattern)."""
    sp = tool_generator._SYSTEM_PROMPT
    assert "call_tool" in sp
    assert "async def" in sp
    assert "learned_tool_dispatch" in sp  # the import path it must use
    assert "Composing other tools" in sp


def test_available_tool_names_excludes_critical(monkeypatch) -> None:
    """The composition surface offered to the generator must drop destructive
    tools — call_tool refuses them at runtime, so never invite them."""
    monkeypatch.setattr(
        "app.services.learning.skill_creator._get_available_tool_names",
        lambda: ["gmail_list_emails", "gmail_send_email", "ssh_execute"],
    )
    monkeypatch.setattr(
        "app.services.learning.learned_tool_dispatch.composable_tool_names",
        lambda: {"gmail_list_emails"},  # the safe subset
    )
    names = tool_generator.get_available_tool_names()
    assert names == ["gmail_list_emails"]


def test_prompt_includes_prior_errors_on_retry() -> None:
    p = compose_user_prompt(
        "do x", available_tools=[], prior_errors="failed at mypy: bad return type"
    )
    assert "PREVIOUS ATTEMPT FAILED" in p
    assert "bad return type" in p


# ── generate_tool_source (mocked tier-S) ────────────────────────────────────────


class _FakeResponse:
    def __init__(self, content: str, in_tok: int = 120, out_tok: int = 60) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": in_tok, "output_tokens": out_tok}
        self.response_metadata = {"model_name": "fake-model"}


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self._content = content
        self.model = "fake-model"

    async def ainvoke(self, messages):
        return _FakeResponse(self._content)


def _patch_llm(monkeypatch, content: str, pick: str = "deepseek") -> None:
    async def _fake_get_llm(*, force_fallback: bool = False):
        return _FakeLLM(content), pick

    monkeypatch.setattr(tool_generator, "get_tier_s_llm", _fake_get_llm)


@pytest.mark.asyncio
async def test_generate_returns_parsed_source(monkeypatch) -> None:
    _patch_llm(monkeypatch, f"```python\n{GENERATED_TOOL}\n```")
    source, info = await generate_tool_source(
        task_description="double a number", user_id="", available_tools=["drive_list_files"]
    )
    assert info["status"] == "generated"
    assert info["provider_pick"] == "deepseek"
    assert source and "def double_it" in source
    # accounting populated from usage_metadata
    assert info["tokens_in"] == 120


@pytest.mark.asyncio
async def test_generate_no_provider(monkeypatch) -> None:
    async def _none_llm(*, force_fallback: bool = False):
        return None, "none"

    monkeypatch.setattr(tool_generator, "get_tier_s_llm", _none_llm)
    source, info = await generate_tool_source(task_description="x", user_id="", available_tools=[])
    assert source is None
    assert info["status"] == "no_provider"


@pytest.mark.asyncio
async def test_generate_llm_failure_is_caught(monkeypatch) -> None:
    class _BoomLLM:
        model = "boom"

        async def ainvoke(self, messages):
            raise RuntimeError("provider down")

    async def _boom(*, force_fallback: bool = False):
        return _BoomLLM(), "deepseek"

    monkeypatch.setattr(tool_generator, "get_tier_s_llm", _boom)
    source, info = await generate_tool_source(task_description="x", user_id="", available_tools=[])
    assert source is None
    assert info["status"] == "llm_call_failed"


@pytest.mark.asyncio
async def test_generate_parse_failure(monkeypatch) -> None:
    _patch_llm(monkeypatch, "Sorry, I won't write that.")
    source, info = await generate_tool_source(task_description="x", user_id="", available_tools=[])
    assert source is None
    assert info["status"] == "parse_failed"


@pytest.mark.asyncio
async def test_generated_tool_passes_validation_chain(monkeypatch) -> None:
    """End-to-end (no real LLM): a generated tool flows into the validator
    and passes all 5 stages."""
    _patch_llm(monkeypatch, f"```python\n{GENERATED_TOOL}\n```")
    source, info = await generate_tool_source(
        task_description="double a number", user_id="", available_tools=[]
    )
    assert info["status"] == "generated"
    report = validate_tool_source(source, existing_names=set(), smoke_kwargs={"x": 21})
    assert report.ok, report.summary()
    assert report.tool_name == "double_it"
