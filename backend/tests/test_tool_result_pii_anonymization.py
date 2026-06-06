# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_result_pii_anonymization.py
# @brief      PII boundary — tool RESULTS are anonymized before going to the
#             LLM (which on tier B/C is a cloud model). The SecurityFilter
#             previously only covered user-TYPED PII; data the agent FETCHED
#             (email bodies, contacts…) reached the model in clear.
# @license    Elastic License 2.0
# =============================================================================
"""tool_node must anonymize tool results with the per-conversation
SecurityFilter before handing them back to the model, and the same shared
filter must be able to deanonymize them for display (chat.py)."""
from __future__ import annotations

import uuid

import pytest

from app.services.conversation_filters import discard_filter, get_filter


@pytest.fixture
def isolated_conv_id():
    conv_id = f"test-conv-{uuid.uuid4().hex}"
    yield conv_id
    discard_filter(conv_id)


class _FakeTool:
    """A non-critical, non-Google tool whose result carries fetched PII."""

    name = "fetch_records"

    async def ainvoke(self, args):  # noqa: ARG002
        return "Contacts: Jean <jean.dupont@example.com>, Marie <marie.curie@example.org>"


class _FakeRegistry:
    @property
    def all_tools(self):
        return [_FakeTool()]


def _patch_registry(monkeypatch):
    monkeypatch.setattr("app.skills.get_skill_registry", lambda: _FakeRegistry())


async def _run(conv_id, monkeypatch):
    from langchain_core.messages import AIMessage

    from app.agent.tool_node import tool_node

    _patch_registry(monkeypatch)
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "fetch_records", "args": {}, "id": "tc-1"}],
    )
    out = await tool_node({
        "messages": [ai], "user_id": "u-1", "conversation_id": conv_id,
    })
    msg = out["messages"][0]
    return msg["content"] if isinstance(msg, dict) else msg.content


@pytest.mark.asyncio
async def test_tool_result_pii_anonymized_before_llm(isolated_conv_id, monkeypatch):
    # Pre-create the conversation filter (same shared instance tool_node uses).
    get_filter(isolated_conv_id)

    content = await _run(isolated_conv_id, monkeypatch)

    # The model NEVER sees the real email addresses.
    assert "jean.dupont@example.com" not in content
    assert "marie.curie@example.org" not in content
    # They were replaced by stable placeholders.
    assert "[EMAIL_" in content

    # Round-trip: the SAME shared filter deanonymizes for display (chat.py:559).
    restored = get_filter(isolated_conv_id).deanonymize(content)
    assert "jean.dupont@example.com" in restored
    assert "marie.curie@example.org" in restored


@pytest.mark.asyncio
async def test_no_conversation_filter_means_no_anonymization(monkeypatch):
    """Documents the boundary: anonymization is conversation-scoped. Without a
    conversation_id (e.g. autonomous missions — separate follow-up), tool
    results are NOT anonymized."""
    content = await _run("", monkeypatch)  # empty conv_id → no filter
    assert "jean.dupont@example.com" in content  # raw — protection is conv-scoped
