"""Tests for tool_call_recovery — fixes models that emit tool calls as
text content instead of structured JSON (audit Option A, 2026-05-06).

Covers Kimi K2 `<tool_call>...</tool_call>`, Qwen DashScope raw JSON,
markdown JSON code fences, hallucinated tool names, and edge cases.
"""
from app.agent.tool_call_recovery import (
    parse_text_tool_calls,
    fuzzy_match_tool_name,
    recover_tool_calls_into_response,
    detect_empty_promise,
)


# ── parse_text_tool_calls ────────────────────────────────────────────────────


def test_parse_kimi_xml_pattern():
    content = '<tool_call>{"name": "browser_screenshot", "arguments": {}}</tool_call>'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["name"] == "browser_screenshot"
    assert calls[0]["arguments"] == {}


def test_parse_kimi_with_args():
    content = (
        'Je vais procéder.\n'
        '<tool_call>\n'
        '{"name": "capture_website", "arguments": {"url": "https://catalogmaker.fr"}}\n'
        '</tool_call>\n'
        '...'
    )
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["name"] == "capture_website"
    assert calls[0]["arguments"]["url"] == "https://catalogmaker.fr"


def test_parse_qwen_raw_json():
    """Qwen 3.6 Flash sometimes emits raw JSON (no wrapping) at start of line."""
    content = (
        'Je vais envoyer la capture par email.\n\n'
        '{\n'
        '"name": "send_email",\n'
        '"arguments": {\n'
        '"to": "follivier@datasolution.fr",\n'
        '"subject": "Capture",\n'
        '"body": "Bonjour"\n'
        '}\n'
        '}'
    )
    calls = parse_text_tool_calls(content)
    assert len(calls) >= 1
    assert calls[0]["name"] == "send_email"
    assert calls[0]["arguments"]["to"] == "follivier@datasolution.fr"


def test_parse_markdown_json_fence():
    content = '```json\n{"name": "gmail_send_email", "arguments": {"to": "x@y.com"}}\n```'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["name"] == "gmail_send_email"


def test_parse_arguments_as_string():
    """Some models stringify the arguments dict."""
    content = '<tool_call>{"name": "x", "arguments": "{\\"k\\": \\"v\\"}"}</tool_call>'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"k": "v"}


def test_parse_invalid_json_returns_empty():
    content = '<tool_call>not even json</tool_call>'
    assert parse_text_tool_calls(content) == []


def test_parse_empty_content():
    assert parse_text_tool_calls("") == []
    assert parse_text_tool_calls(None) == []  # type: ignore[arg-type]


def test_parse_no_tool_calls_in_normal_text():
    content = "Bonjour Franck, comment puis-je t'aider ?"
    assert parse_text_tool_calls(content) == []


def test_parse_function_call_alternative():
    content = '<function_call>{"name": "browser_navigate", "arguments": {"url": "https://x.com"}}</function_call>'
    calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["name"] == "browser_navigate"


# ── fuzzy_match_tool_name ────────────────────────────────────────────────────


def test_fuzzy_exact_match():
    real = {"gmail_send_email", "browser_screenshot"}
    assert fuzzy_match_tool_name("gmail_send_email", real) == "gmail_send_email"


def test_fuzzy_substring_match():
    real = {"gmail_send_email", "browser_screenshot"}
    assert fuzzy_match_tool_name("send_email", real) == "gmail_send_email"


def test_fuzzy_semantic_capture_website():
    real = {"browser_screenshot", "browser_navigate", "gmail_send_email"}
    assert fuzzy_match_tool_name("capture_website", real) == "browser_screenshot"


def test_fuzzy_semantic_take_screenshot():
    real = {"browser_screenshot", "os_screenshot"}
    # Should match browser_screenshot first (priority order in _SEMANTIC_HINTS)
    result = fuzzy_match_tool_name("take_screenshot", real)
    assert result in {"browser_screenshot", "os_screenshot"}


def test_fuzzy_no_match_below_threshold():
    real = {"gmail_send_email"}
    # "totally_random_name" is too different
    assert fuzzy_match_tool_name("xyzqwerty", real) is None


def test_fuzzy_empty_inputs():
    assert fuzzy_match_tool_name("", {"a"}) is None
    assert fuzzy_match_tool_name("a", set()) is None


# ── recover_tool_calls_into_response ─────────────────────────────────────────


class _MockResponse:
    """Stand-in for AIMessage with `content` and `tool_calls` attributes."""
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def test_recover_kimi_pattern():
    content = '<tool_call>{"name": "send_email", "arguments": {"to": "x@y.com"}}</tool_call>'
    resp = _MockResponse(content)
    real_names = {"gmail_send_email", "browser_screenshot"}
    n = recover_tool_calls_into_response(resp, real_names)
    assert n == 1
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "gmail_send_email"  # rewritten via fuzzy
    assert resp.tool_calls[0]["args"] == {"to": "x@y.com"}


def test_recover_skipped_when_tool_calls_already_present():
    """If model already populated tool_calls properly, don't touch."""
    resp = _MockResponse(
        content='<tool_call>{"name": "X", "arguments": {}}</tool_call>',
        tool_calls=[{"name": "real_call", "args": {}, "id": "abc", "type": "tool_call"}],
    )
    n = recover_tool_calls_into_response(resp, {"real_call"})
    assert n == 0
    assert resp.tool_calls[0]["name"] == "real_call"  # unchanged


def test_recover_skips_unknown_tool():
    """If hallucinated name has no fuzzy match, skip it."""
    content = '<tool_call>{"name": "totally_invented_tool_xyzabc", "arguments": {}}</tool_call>'
    resp = _MockResponse(content)
    n = recover_tool_calls_into_response(resp, {"gmail_send_email"})
    assert n == 0
    assert resp.tool_calls == []


def test_recover_strips_json_from_content():
    """After recovery, the raw JSON should not be visible to the user."""
    content = '<tool_call>{"name": "send_email", "arguments": {}}</tool_call>'
    resp = _MockResponse(content)
    recover_tool_calls_into_response(resp, {"gmail_send_email"})
    assert "tool_call" not in resp.content.lower()


# ── detect_empty_promise ─────────────────────────────────────────────────────


def test_empty_promise_french_drive():
    assert detect_empty_promise(
        "Je télécharge la capture sur ton Drive…"
    ) is True


def test_empty_promise_french_mail():
    assert detect_empty_promise(
        "Je m'en occupe immédiatement. Envoi en cours du mail à franck."
    ) is True


def test_empty_promise_french_save_disk():
    assert detect_empty_promise(
        "Je vais sauvegarder le fichier sur ton disque dur"
    ) is True


def test_empty_promise_english_uploading():
    assert detect_empty_promise(
        "I'm uploading the screenshot to your Drive now"
    ) is True


def test_empty_promise_english_will_send():
    assert detect_empty_promise(
        "I'll send the file by email shortly"
    ) is True


def test_empty_promise_no_target():
    """Promise verb but no delivery target → not flagged."""
    assert detect_empty_promise(
        "Je vais réfléchir à ton problème"
    ) is False


def test_empty_promise_no_verb():
    """Delivery target mentioned but no promise verb → not flagged."""
    assert detect_empty_promise(
        "Le fichier est sur ton Drive, j'ai vérifié."
    ) is False


def test_empty_promise_legitimate_question():
    """Asking the user is not a promise."""
    assert detect_empty_promise(
        "Veux-tu que j'envoie ce fichier par mail ?"
    ) is False


def test_empty_promise_real_status_report():
    """Past tense / completed action — not a hollow promise."""
    assert detect_empty_promise(
        "J'ai envoyé le mail et sauvegardé la capture sur Drive."
    ) is False


def test_empty_promise_empty():
    assert detect_empty_promise("") is False
    assert detect_empty_promise(None) is False  # type: ignore[arg-type]
