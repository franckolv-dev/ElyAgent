# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_model_metadata.py
# @brief      Métadonnées modèles — capacités vision/contexte, wiring supports_vision
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for the model-metadata source of truth + supports_vision wiring."""
from __future__ import annotations

import pytest

from app.services.model_metadata import (
    ModelCapabilities,
    _parse_models_dev,
    context_window,
    get_capabilities,
    vision_capability,
)


# ── snapshot lookups (the core value) ────────────────────────────────────────

@pytest.mark.parametrize("provider,model,expected", [
    ("anthropic", "claude-haiku-4", True),
    ("anthropic", "claude-sonnet-4-6", True),
    ("gemini", "gemini-2.5-flash", True),
    ("openai", "gpt-4o", True),
    ("openai-codex", "gpt-5.5", True),
    ("mistral", "pixtral-12b", True),
    ("qwen_api", "qwen2.5-vl-7b", True),
    ("lm_studio", "gemma-4-e4b-it-mlx@8bit", True),   # local multimodal + quant suffix
    # text-only
    ("deepseek", "deepseek-v4-pro", False),
    ("deepseek", "deepseek-v4-flash", False),
    ("lm_studio", "mistralai/devstral-small-2-2512", False),  # provider prefix
    ("qwen_api", "qwen3.6-flash", False),             # non-VL qwen = text
    ("lm_studio", "lfm2.5-8b-a1b-mlx", False),
])
def test_snapshot_vision(provider, model, expected):
    assert vision_capability(provider, model) is expected


def test_unknown_model_returns_none():
    # Truly unknown → None so the caller can fall back to its heuristic.
    assert get_capabilities("x", "totally-made-up-model-xyz") is None
    assert vision_capability("x", "totally-made-up-model-xyz") is None


def test_context_window_known():
    assert context_window("anthropic", "claude-sonnet-4-6") == 200_000
    assert context_window("gemini", "gemini-2.5-flash") == 1_000_000
    assert context_window("x", "unknown") is None


# ── models.dev parsing (the overlay source) ──────────────────────────────────

def test_parse_models_dev():
    sample = {
        "anthropic": {
            "models": {
                "claude-4-haiku": {
                    "modalities": {"input": ["text", "image"]},
                    "limit": {"context": 200000, "output": 8192},
                    "cost": {"input": 0.8, "output": 4.0},
                    "tool_call": True,
                },
            },
        },
        "deepseek": {
            "models": {
                "deepseek-chat": {
                    "modalities": {"input": ["text"]},
                    "limit": {"context": 128000},
                    "tool_call": True,
                },
            },
        },
        "broken": {"models": "not-a-dict"},   # must be skipped, no crash
    }
    out = _parse_models_dev(sample)
    assert out["claude-4-haiku"]["vision"] is True
    assert out["claude-4-haiku"]["context_window"] == 200000
    assert out["claude-4-haiku"]["input_per_m"] == 0.8
    assert out["deepseek-chat"]["vision"] is False
    assert "not-a-dict" not in out


def test_parse_models_dev_garbage():
    assert _parse_models_dev({}) == {}
    assert _parse_models_dev("nope") == {}  # type: ignore[arg-type]


# ── supports_vision wiring (metadata first, heuristic fallback) ───────────────

def test_supports_vision_uses_metadata(monkeypatch):
    import app.services.llm_provider as lp

    # Known text-only model → metadata says False (even though the heuristic
    # has no opinion).
    monkeypatch.setattr(lp, "describe_llm", lambda _llm: ("deepseek", "deepseek-v4-pro"))
    assert lp.supports_vision(object()) is False

    # Known vision model → metadata says True.
    monkeypatch.setattr(lp, "describe_llm", lambda _llm: ("anthropic", "claude-haiku-4"))
    assert lp.supports_vision(object()) is True


def test_supports_vision_falls_back_to_heuristic(monkeypatch):
    import app.services.llm_provider as lp
    # A model unknown to the snapshot but caught by the legacy pattern list
    # (kimi-thinking-preview) must still resolve via the heuristic.
    monkeypatch.setattr(lp, "describe_llm", lambda _llm: ("moonshot", "kimi-thinking-preview"))
    assert lp.supports_vision(object()) is True


def test_capabilities_dataclass_defaults():
    c = ModelCapabilities()
    assert c.vision is None and c.source == "snapshot"
