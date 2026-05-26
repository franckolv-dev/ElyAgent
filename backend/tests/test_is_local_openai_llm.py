# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_is_local_openai_llm.py
# @brief      Pin the `is_local_openai_llm` heuristic that gates the H-1
#             anti-hallucination guard. A false-positive here demotes a
#             working cloud LLM onto its fallback for the rest of the
#             conversation — observed in prod 2026-05-25 on DeepSeek-pro
#             (conv e9b33b7d stuck on Claude Haiku for 1h+).
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `app.services.qwen_no_think.is_local_openai_llm`.

The function is used in two critical places :
1. The H-1 anti-hallucination guard in `agent_node` — if it false-
   positives on a cloud LLM, the cloud LLM gets unjustly demoted to
   its fallback for the whole conversation (sticky behaviour).
2. The "compact prompt" gate that swaps the 12k-char system prompt for
   a 200-token compact version when the active LLM is local.

A wrong answer in either direction has user-visible consequences.
"""
from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from app.services.qwen_no_think import is_local_openai_llm


def _make_chat_openai(*, model: str, base_url: str) -> ChatOpenAI:
    """Minimal ChatOpenAI factory for the tests. No real network."""
    return ChatOpenAI(model=model, api_key="test-fake-key", base_url=base_url)


# ─────────────────────────────────────────────────────────────────────────
# Real cloud LLMs must return False
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model,base_url", [
    # The exact case from the prod incident 2026-05-25 conv e9b33b7d
    ("deepseek-chat", "https://api.deepseek.com/v1"),
    ("deepseek-v4-pro", "https://api.deepseek.com/v1"),
    ("deepseek-v4-flash", "https://api.deepseek.com/v1"),
    # Other known cloud providers we route to
    ("gpt-4o", "https://api.openai.com/v1"),
    ("gpt-4-turbo", "https://api.openai.com/v1"),
    ("kimi-k2.6", "https://api.moonshot.ai/v1"),
    ("qwen3.6-flash", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    ("qwen3-vl-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("glm-4", "https://open.bigmodel.cn/api/paas/v4/"),
    # Generic cloud Anthropic-style proxy
    ("claude-haiku-4-5", "https://api.anthropic.com/v1"),
    # Mistral (Ministral / Mistral-large variants are common)
    ("mistral-large-latest", "https://api.mistral.ai/v1"),
])
def test_real_cloud_llm_returns_false(model: str, base_url: str) -> None:
    llm = _make_chat_openai(model=model, base_url=base_url)
    assert is_local_openai_llm(llm) is False, (
        f"Cloud LLM {model} @ {base_url} should NOT be flagged as local — "
        f"a false-positive demotes the conv to its fallback for the rest "
        f"of the session (observed prod incident 2026-05-25)"
    )


# ─────────────────────────────────────────────────────────────────────────
# Real local servers must return True
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model,base_url", [
    # LM Studio default
    ("gemma-4-E4B-it-MLX-8bit", "http://localhost:1234/v1"),
    ("ministral-3-3b-instruct", "http://127.0.0.1:1234/v1"),
    ("xLAM-2-8b-fc-r-mlx", "http://localhost:1234/v1"),
    # llama.cpp server
    ("llama-3-8b", "http://localhost:8080/v1"),
    # vLLM on Mac Studio LAN
    ("qwen-3-7b", "http://192.168.1.42:8000/v1"),
    # Docker bridge networks
    ("gemma-4-E4B-it-MLX-4bit", "http://172.18.0.5:1234/v1"),
    # Generic .local mDNS
    ("custom-mlx", "http://macstudio.local:1234/v1"),
])
def test_local_server_returns_true(model: str, base_url: str) -> None:
    llm = _make_chat_openai(model=model, base_url=base_url)
    assert is_local_openai_llm(llm) is True, (
        f"Local server {model} @ {base_url} should be detected as local — "
        f"failure here disables the H-1 anti-hallucination guard"
    )


# ─────────────────────────────────────────────────────────────────────────
# Edge cases that used to false-positive with the previous "10." marker
# ─────────────────────────────────────────────────────────────────────────


def test_cloud_url_with_port_10080_is_not_local() -> None:
    """Previously the short ``"10."`` marker matched ``:10080`` in ports."""
    llm = _make_chat_openai(
        model="deepseek-chat",
        base_url="https://api.deepseek.com:10080/v1",
    )
    assert is_local_openai_llm(llm) is False


def test_cloud_url_with_v10_path_segment_is_not_local() -> None:
    """Previously ``"10."`` matched ``/v10/``."""
    llm = _make_chat_openai(
        model="gpt-4-turbo",
        base_url="https://api.example.com/v10/",
    )
    assert is_local_openai_llm(llm) is False


# ─────────────────────────────────────────────────────────────────────────
# Cloud-model-name veto — defence-in-depth
# ─────────────────────────────────────────────────────────────────────────


def test_cloud_model_name_wins_over_suspicious_url() -> None:
    """Even if a cloud LLM is somehow served through a reverse-proxy on a
    private IP (e.g. Docker bridge → DeepSeek), the model name should win
    and prevent the local classification. Otherwise H-1 would fire on a
    cloud LLM because its proxied URL contains 192.168.* or similar."""
    llm = _make_chat_openai(
        model="deepseek-v4-pro",
        base_url="http://192.168.1.99:8080/v1",  # private IP proxy
    )
    assert is_local_openai_llm(llm) is False, (
        "deepseek-v4-pro should win the veto even if served on a private IP"
    )


def test_claude_via_anthropic_compat_proxy_is_not_local() -> None:
    llm = _make_chat_openai(
        model="claude-haiku-4-5-20251001",
        base_url="http://10.0.0.5:8080/v1",
    )
    assert is_local_openai_llm(llm) is False


# ─────────────────────────────────────────────────────────────────────────
# Defensive cases
# ─────────────────────────────────────────────────────────────────────────


def test_none_llm_returns_false() -> None:
    assert is_local_openai_llm(None) is False


def test_non_chatopenai_returns_false() -> None:
    """A LangChain wrapper that isn't ChatOpenAI is automatically False
    (we only have data to reason about ChatOpenAI instances)."""
    class _Stub:
        base_url = "http://localhost:1234/v1"
    assert is_local_openai_llm(_Stub()) is False


def test_empty_base_url_returns_false() -> None:
    """If we can't introspect the base_url, fall back to False (safer)."""
    llm = ChatOpenAI(model="some-model", api_key="x")
    # Default ChatOpenAI base_url is openai.com — not local
    assert is_local_openai_llm(llm) is False
