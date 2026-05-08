# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_tool_result_sanitize.py
# @brief      Tests for _sanitize_tool_result_for_history
# =============================================================================
"""Tests for the heavy-payload stripper used by ``tool_node``.

Critical : without it, ``browser_screenshot`` and similar tools that return
base64 image data flood the model's context at the next turn.

Observed 2026-05-08 :
- Qwen 2.5 14B local : 216 000 tokens → TruncateMiddle → workflow collapse
- Qwen 3.6 Flash via DashScope : tour 2 lent (re-tokenisation du base64)

The frontend's ``on_tool_end`` event still receives the full original
payload — only the tool message stored in LangGraph state is trimmed.
"""
from __future__ import annotations

import json

import pytest

from app.agent.nodes import (
    _HEAVY_FIELD_THRESHOLD,
    _sanitize_tool_result_for_history,
)


def _big_b64(n_chars: int = _HEAVY_FIELD_THRESHOLD + 1000) -> str:
    """Synthetic base64-ish payload."""
    return "iVBORw0KGgoAAAANSUhEUgAA" + ("A" * n_chars)


# ──────────────────────────────────────────────────────────────────────────────
# Heavy field detection / replacement
# ──────────────────────────────────────────────────────────────────────────────


def test_strips_oversized_data_field():
    payload = json.dumps({
        "type": "image",
        "data": _big_b64(),
        "mime": "image/png",
        "local_path": "/tmp/ely-attachments/screenshot-abc.png",
        "next_steps": "use local_path with gmail_send_with_local_attachment",
    })
    result = _sanitize_tool_result_for_history(payload)
    obj = json.loads(result)
    # data is replaced by a marker; everything else preserved
    assert "stripped" in obj["data"]
    assert "kept in frontend payload" in obj["data"]
    assert obj["mime"] == "image/png"
    assert obj["local_path"] == "/tmp/ely-attachments/screenshot-abc.png"
    assert "next_steps" in obj
    # Net token saving is huge
    assert len(result) < len(payload) // 4


def test_preserves_small_data_field():
    """Below threshold, ``data`` is left intact (could be a tiny icon)."""
    small_data = "iVBORw=="  # 8 chars
    payload = json.dumps({"data": small_data, "mime": "image/png"})
    result = _sanitize_tool_result_for_history(payload)
    obj = json.loads(result)
    assert obj["data"] == small_data


@pytest.mark.parametrize("heavy_key", [
    "data", "b64", "b64_json", "image_data", "binary", "raw",
])
def test_strips_all_heavy_field_aliases(heavy_key):
    payload = json.dumps({heavy_key: _big_b64(), "url": "x"})
    result = _sanitize_tool_result_for_history(payload)
    obj = json.loads(result)
    assert "stripped" in obj[heavy_key]
    assert obj["url"] == "x"


def test_strips_multiple_heavy_fields_in_same_payload():
    payload = json.dumps({
        "data": _big_b64(),
        "raw": _big_b64(8000),
        "thumbnail_path": "/tmp/ely-attachments/thumb.png",
    })
    result = _sanitize_tool_result_for_history(payload)
    obj = json.loads(result)
    assert "stripped" in obj["data"]
    assert "stripped" in obj["raw"]
    assert obj["thumbnail_path"] == "/tmp/ely-attachments/thumb.png"


# ──────────────────────────────────────────────────────────────────────────────
# Pass-through / edge cases
# ──────────────────────────────────────────────────────────────────────────────


def test_non_json_string_unchanged():
    text = "Capture sauvegardée. Le fichier est /tmp/ely-attachments/x.png"
    assert _sanitize_tool_result_for_history(text) == text


def test_non_dict_json_unchanged():
    text = json.dumps([1, 2, 3])  # JSON array, not a dict
    assert _sanitize_tool_result_for_history(text) == text


def test_malformed_json_unchanged():
    text = "{not valid json at all"
    assert _sanitize_tool_result_for_history(text) == text


def test_empty_input_unchanged():
    assert _sanitize_tool_result_for_history("") == ""


def test_dict_without_heavy_fields_unchanged():
    payload = json.dumps({
        "url": "https://example.com",
        "title": "Example",
        "local_path": "/tmp/ely-attachments/x.png",
    })
    assert _sanitize_tool_result_for_history(payload) == payload


def test_handles_non_string_input():
    """The helper must not crash on weird inputs."""
    assert _sanitize_tool_result_for_history(None) is None  # type: ignore[arg-type]


def test_returns_valid_json_after_strip():
    """The output must remain parseable JSON so downstream code works."""
    payload = json.dumps({
        "type": "image",
        "data": _big_b64(),
        "mime": "image/png",
    })
    result = _sanitize_tool_result_for_history(payload)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_preserves_unicode_content():
    """French / emoji content survives the round-trip."""
    payload = json.dumps({
        "data": _big_b64(),
        "next_steps": "Utilise local_path pour envoyer par mail 📧",
    }, ensure_ascii=False)
    result = _sanitize_tool_result_for_history(payload)
    obj = json.loads(result)
    assert "📧" in obj["next_steps"]
    assert "Utilise local_path" in obj["next_steps"]


def test_screenshot_real_payload_shape():
    """End-to-end : the exact shape browser_screenshot returns."""
    payload = json.dumps({
        "type": "image",
        "data": _big_b64(180_000),  # 180 KB → ~45k tokens
        "mime": "image/png",
        "prompt": "Capture d'écran — BAT+ (https://catalogmaker.fr)",
        "local_path": "/tmp/ely-attachments/screenshot-abc123.png",
        "attachment_id": "abc123",
        "next_steps": (
            "Capture sauvegardée. Pour livrer le fichier au user, "
            "applique l'UNE des actions suivantes : ..."
        ),
    })
    sanitised = _sanitize_tool_result_for_history(payload)
    assert len(sanitised) < 1000, (
        f"sanitised payload should be tiny; got {len(sanitised)} chars"
    )
    obj = json.loads(sanitised)
    # Critical fields preserved for the model to chain calls
    assert obj["local_path"] == "/tmp/ely-attachments/screenshot-abc123.png"
    assert obj["attachment_id"] == "abc123"
    assert obj["mime"] == "image/png"
    assert "next_steps" in obj
