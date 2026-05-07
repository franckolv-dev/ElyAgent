"""Tests for vision_injection — injects screenshot images for vision-capable LLMs."""
import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.agent.vision_injection import (
    _extract_image_from_tool_msg,
    maybe_inject_screenshot,
)


# ── _extract_image_from_tool_msg ──────────────────────────────────────────────


def test_extract_from_string_json():
    content = json.dumps({
        "type": "image",
        "data": "iVBORw0KGgoAAAANSU=",
        "mime": "image/png",
        "prompt": "test",
    })
    result = _extract_image_from_tool_msg(content)
    assert result == ("image/png", "iVBORw0KGgoAAAANSU=")


def test_extract_default_mime():
    content = json.dumps({"type": "image", "data": "abc"})
    result = _extract_image_from_tool_msg(content)
    assert result == ("image/png", "abc")


def test_extract_rejects_non_image():
    content = json.dumps({"type": "text", "data": "hello"})
    assert _extract_image_from_tool_msg(content) is None


def test_extract_rejects_invalid_json():
    assert _extract_image_from_tool_msg("not json") is None
    assert _extract_image_from_tool_msg("plain text result") is None


def test_extract_rejects_missing_data():
    content = json.dumps({"type": "image"})
    assert _extract_image_from_tool_msg(content) is None


def test_extract_from_list_blocks():
    content = [
        {"type": "text", "text": "Voici la capture"},
        {"type": "image", "data": "xxx", "mime": "image/jpeg"},
    ]
    result = _extract_image_from_tool_msg(content)
    assert result == ("image/jpeg", "xxx")


# ── maybe_inject_screenshot ───────────────────────────────────────────────────


class _FakeNonVisionLLM:
    """Stand-in for Ministral / Qwen-non-VL etc."""
    model = "ministral-3-8b-instruct"
    __class__ = type("ChatOpenAI", (), {"__name__": "ChatOpenAI"})


class _FakeVisionLLM:
    """Stand-in for Pixtral / Qwen-VL / GPT-4o etc."""
    model = "qwen3-vl-8b"
    openai_api_base = "http://localhost:1234/v1"

    def __init__(self):
        self.__class__.__name__ = "ChatOpenAI"


def test_inject_skipped_for_non_vision_model():
    """Non-vision model: messages returned unchanged."""
    msgs = [
        HumanMessage(content="capture catalogmaker.fr"),
        ToolMessage(
            content=json.dumps({"type": "image", "data": "xxx", "mime": "image/png"}),
            tool_call_id="tc1",
        ),
    ]
    llm = _FakeNonVisionLLM()
    result = maybe_inject_screenshot(msgs, llm)
    assert result is msgs or len(result) == len(msgs)


def test_inject_adds_human_message_for_vision_model(monkeypatch):
    """Vision model + recent screenshot tool → HumanMessage with image_url."""
    # Enable injection (opt-in by default since 2026-05-07)
    monkeypatch.setattr("app.agent.vision_injection._ENABLED", True)
    # Force supports_vision=True without monkey-patching the whole llm chain
    monkeypatch.setattr(
        "app.services.llm_provider.supports_vision",
        lambda llm: True,
    )
    msgs = [
        HumanMessage(content="capture catalogmaker.fr"),
        ToolMessage(
            content=json.dumps({
                "type": "image",
                "data": "iVBORw0KGgo=",
                "mime": "image/png",
            }),
            tool_call_id="tc1",
        ),
    ]
    result = maybe_inject_screenshot(msgs, llm=object())
    assert len(result) == len(msgs) + 1
    injected = result[-1]
    assert isinstance(injected, HumanMessage)
    # Multimodal content: list with text + image_url blocks
    assert isinstance(injected.content, list)
    assert any(b.get("type") == "image_url" for b in injected.content)
    img_block = next(b for b in injected.content if b.get("type") == "image_url")
    assert img_block["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="


def test_inject_skipped_when_no_recent_screenshot(monkeypatch):
    """Vision model but no recent tool message with image → no injection."""
    monkeypatch.setattr("app.agent.vision_injection._ENABLED", True)
    monkeypatch.setattr(
        "app.services.llm_provider.supports_vision",
        lambda llm: True,
    )
    msgs = [HumanMessage(content="bonjour")]
    result = maybe_inject_screenshot(msgs, llm=object())
    assert len(result) == len(msgs)


def test_inject_only_latest_screenshot(monkeypatch):
    """Multiple screenshots: only the last one is injected (token economy)."""
    monkeypatch.setattr("app.agent.vision_injection._ENABLED", True)
    monkeypatch.setattr(
        "app.services.llm_provider.supports_vision",
        lambda llm: True,
    )
    msgs = [
        HumanMessage(content="capture x.com"),
        ToolMessage(content=json.dumps({"type": "image", "data": "old", "mime": "image/png"}),
                    tool_call_id="tc1"),
        ToolMessage(content=json.dumps({"type": "image", "data": "new", "mime": "image/png"}),
                    tool_call_id="tc2"),
    ]
    result = maybe_inject_screenshot(msgs, llm=object())
    assert len(result) == len(msgs) + 1
    img_block = next(b for b in result[-1].content if b.get("type") == "image_url")
    assert "new" in img_block["image_url"]["url"]
    assert "old" not in img_block["image_url"]["url"]
