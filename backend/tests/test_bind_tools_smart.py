# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_bind_tools_smart.py
# @brief      Tests for _bind_tools_smart (parallel_tool_calls policy)
# =============================================================================
"""Tests for the smart bind_tools wrapper that disables
``parallel_tool_calls`` for permissive and OpenAI-family models.

Bug observed 2026-05-08 on Qwen 2.5 14B local : the model emitted
3 tool_calls in parallel including ``gmail_send_with_local_attachment``
with an INVENTED ``local_path`` (because it had no way to know what
``browser_screenshot`` would later return). With ``parallel_tool_calls=False``,
the model emits one call per turn and chains correctly.

Diagnostic 2026-05-08 (post-rollback) confirmed in container :
- ``langchain-openai 1.1.10`` accepts ``parallel_tool_calls=False`` at bind
- LM Studio (Qwen 2.5 14B) accepts it in the request body
- Real ainvoke round-trip works end-to-end

This re-introduction has WARNING-level logging on every code path so any
future silent failure produces a stack trace in the container logs.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent.nodes import (
    _bind_tools_smart,
    _classify_model_family,
    _extract_model_name,
)


# ──────────────────────────────────────────────────────────────────────────────
# _classify_model_family
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model_name, expected", [
    # Disciplined — Claude / Anthropic
    ("claude-sonnet-4-6",                  "disciplined"),
    ("claude-haiku-4-5-20251001",          "disciplined"),
    ("anthropic/claude-3-5-sonnet",        "disciplined"),
    ("Claude-Sonnet-4.6",                  "disciplined"),  # case-insensitive
    # OpenAI family
    ("gpt-4o",                              "openai_family"),
    ("gpt-4o-mini",                         "openai_family"),
    ("openai/gpt-4-turbo",                  "openai_family"),
    ("mlx-community/gpt-oss-20b-MXFP4-Q8",  "openai_family"),
    ("codex-1-large",                       "openai_family"),
    ("o1-preview",                          "openai_family"),
    ("o3-mini",                             "openai_family"),
    # Permissive — everything else
    ("qwen-plus-latest",                    "permissive"),
    ("Qwen2.5-14B-Instruct-4bit",           "permissive"),
    ("qwen3.6-flash",                       "permissive"),
    ("mistral-small-latest",                "permissive"),
    ("ministral-3-8b-instruct",             "permissive"),
    ("gemma-4-26B-A4B-it-MLX",              "permissive"),
    ("gemini-2.5-flash",                    "permissive"),
    ("meta-llama/llama-3.3-70b-instruct",   "permissive"),
    ("glm-4.7",                             "permissive"),
    ("deepseek-v3",                         "permissive"),
])
def test_classify_model_family(model_name, expected):
    assert _classify_model_family(model_name) == expected


@pytest.mark.parametrize("falsy", [None, "", "   "])
def test_classify_falsy_inputs_default_to_permissive(falsy):
    assert _classify_model_family(falsy) == "permissive"


# ──────────────────────────────────────────────────────────────────────────────
# _extract_model_name
# ──────────────────────────────────────────────────────────────────────────────


def test_extract_model_name_from_model_name_attr():
    llm = MagicMock(spec=["model_name"])
    llm.model_name = "qwen-plus-latest"
    assert _extract_model_name(llm) == "qwen-plus-latest"


def test_extract_model_name_falls_back_to_model_attr():
    """``model`` is the attribute on ChatAnthropic / ChatOllama."""
    llm = MagicMock(spec=["model"])
    llm.model = "claude-sonnet-4-6"
    assert _extract_model_name(llm) == "claude-sonnet-4-6"


def test_extract_model_name_handles_none():
    assert _extract_model_name(None) == ""


def test_extract_model_name_handles_no_attribute():
    """An LLM without any of the known attributes returns empty string."""
    class _Bare:
        pass
    assert _extract_model_name(_Bare()) == ""


# ──────────────────────────────────────────────────────────────────────────────
# _bind_tools_smart
# ──────────────────────────────────────────────────────────────────────────────


class _FakeLLM:
    """Minimal stand-in for a langchain ChatModel."""

    def __init__(self, accepts_parallel: bool = True, model: str = "test-model") -> None:
        self.accepts_parallel = accepts_parallel
        self.model_name = model
        self.last_call: dict = {}

    def bind_tools(self, tools, **kwargs):
        if "parallel_tool_calls" in kwargs and not self.accepts_parallel:
            raise TypeError(
                "bind_tools() got an unexpected keyword argument 'parallel_tool_calls'"
            )
        self.last_call = {"tools": tools, "kwargs": kwargs}
        return MagicMock(name="bound_llm")


_TOOLS = [MagicMock(name="tool1"), MagicMock(name="tool2"), MagicMock(name="tool3")]


@pytest.mark.parametrize("model_name", [
    "qwen-plus-latest",
    "Qwen2.5-14B-Instruct-4bit",
    "mistral-small-latest",
    "ministral-3-8b-instruct",
    "gemma-4-26B",
    "gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek-v3",
])
def test_permissive_models_disable_parallel(model_name):
    """All permissive models receive parallel_tool_calls=False."""
    llm = _FakeLLM(accepts_parallel=True, model=model_name)
    _bind_tools_smart(llm, _TOOLS, model_name=model_name)
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False


@pytest.mark.parametrize("model_name", [
    "gpt-4o",
    "gpt-4o-mini",
    "openai/gpt-oss-20b",
    "mlx-community/gpt-oss-20b-MXFP4-Q8",
    "codex-1-large",
    "o1-preview",
    "o3-mini",
])
def test_openai_family_disables_parallel(model_name):
    llm = _FakeLLM(accepts_parallel=True, model=model_name)
    _bind_tools_smart(llm, _TOOLS, model_name=model_name)
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False


@pytest.mark.parametrize("model_name", [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "anthropic/claude-3-5-sonnet",
])
def test_disciplined_models_keep_default(model_name):
    """Claude / Anthropic must NOT receive the parallel kwarg.

    Their bind_tools doesn't accept it ; passing it would raise TypeError.
    Default behaviour (parallel allowed) is correct for Claude.
    """
    llm = _FakeLLM(accepts_parallel=False, model=model_name)
    _bind_tools_smart(llm, _TOOLS, model_name=model_name)
    assert "parallel_tool_calls" not in llm.last_call["kwargs"]


def test_falls_back_gracefully_when_kwarg_unsupported():
    """Permissive-classified provider whose bind_tools rejects the kwarg
    still gets bound, without crashing."""
    llm = _FakeLLM(accepts_parallel=False, model="qwen-plus-latest")
    bound = _bind_tools_smart(llm, _TOOLS, model_name="qwen-plus-latest")
    assert bound is not None
    # Final call to bind_tools succeeded WITHOUT the kwarg
    assert "parallel_tool_calls" not in llm.last_call["kwargs"]


def test_unknown_model_name_defaults_to_permissive():
    llm = _FakeLLM(accepts_parallel=True, model="weird-unseen-model-xyz")
    _bind_tools_smart(llm, _TOOLS, model_name="weird-unseen-model-xyz")
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False


def test_none_model_name_extracts_from_llm_instance():
    """When model_name is None, the helper inspects the llm directly."""
    llm = _FakeLLM(accepts_parallel=True, model="qwen-test-7b")
    _bind_tools_smart(llm, _TOOLS, model_name=None)
    # Auto-detected as permissive → kwarg passed
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False


def test_none_model_name_no_attribute_defaults_permissive():
    """If neither model_name argument nor llm attribute → still works."""
    class _BareLLM:
        def bind_tools(self, tools, **kwargs):
            self.last_call = {"tools": tools, "kwargs": kwargs}
            return MagicMock(name="bound")

    llm = _BareLLM()
    _bind_tools_smart(llm, _TOOLS)
    # Default permissive → kwarg passed
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False


def test_returns_bound_llm():
    llm = _FakeLLM(model="claude-sonnet-4-6")
    result = _bind_tools_smart(llm, _TOOLS, model_name="claude-sonnet-4-6")
    assert result is not None
    assert llm.last_call["tools"] is _TOOLS


# ──────────────────────────────────────────────────────────────────────────────
# Defensive paths
# ──────────────────────────────────────────────────────────────────────────────


def test_helper_catches_runtime_error_on_parametrised_bind():
    """If bind_tools raises RuntimeError (not TypeError) when given the kwarg,
    the helper still falls back to plain bind without crashing."""
    class _PickyLLM:
        def __init__(self):
            self.calls = 0
        @property
        def model_name(self):
            return "qwen-2.5-14b"
        def bind_tools(self, tools, **kwargs):
            self.calls += 1
            if "parallel_tool_calls" in kwargs:
                raise RuntimeError("provider rejected parameter at runtime")
            return MagicMock(name="bound")

    llm = _PickyLLM()
    bound = _bind_tools_smart(llm, _TOOLS)
    assert bound is not None
    # 2 calls : 1 with kwarg (failed), 1 without (succeeded)
    assert llm.calls == 2


def test_plain_bind_failure_propagates():
    """If even the plain bind_tools raises, the exception propagates —
    we have no further fallback path beyond that."""
    class _BrokenLLM:
        @property
        def model_name(self):
            return "claude-sonnet-4-6"  # disciplined → tries plain bind first
        def bind_tools(self, tools, **kwargs):
            raise ValueError("totally broken")

    with pytest.raises(ValueError, match="totally broken"):
        _bind_tools_smart(_BrokenLLM(), _TOOLS)


def test_explicit_model_name_overrides_llm_attribute():
    """Caller can force a specific model_name even if llm has another attr."""
    llm = _FakeLLM(accepts_parallel=True, model="claude-sonnet-4-6")
    _bind_tools_smart(llm, _TOOLS, model_name="qwen-plus")
    # qwen-plus → permissive → kwarg passed
    assert llm.last_call["kwargs"].get("parallel_tool_calls") is False
