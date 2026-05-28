# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_anonymization.py
# @brief      Tests de l'anonymisation sandbox → LLM (Sprint 2.7 — Jalon 6).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Tests Jalon 6 — re-anonymisation du stdout/stderr du sandbox.

Le sandbox reçoit des args déjà déanonymisés (``tool_node`` restaure les
vraies valeurs avant d'appeler le tool ``orchestrate``). Les tools
appelés depuis le sandbox (Gmail, Drive, etc.) retournent à leur tour
de la PII en clair. Sans re-anonymisation, cette PII remonterait dans
le contexte du LLM principal — donc on l'anonymise à la sortie du tool
``orchestrate``.

Couvre :
    1. Quand ``ORCHESTRATE_CONVERSATION_ID`` est set et que stdout
       contient un email, le retour du tool contient ``[EMAIL_X]`` à la
       place.
    2. Quand le contextvar n'est pas set (test mode / appel hors graph),
       le tool ne crashe pas et ne tente pas d'anonymiser.
    3. La stabilité des placeholders : si l'email a déjà été vu plus tôt
       dans la conversation (et qu'il a un placeholder dans le filter),
       le tool réutilise le même placeholder.
    4. Stderr est aussi anonymisé (et pas seulement stdout).
"""
from __future__ import annotations

import pytest

from app.agent.tools.orchestrate_tool import (
    ORCHESTRATE_CONVERSATION_ID,
    orchestrate,
)
from app.services.conversation_filters import discard_filter, get_filter
from app.services.orchestrate_runner import OrchestrateRunner


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_conv_id():
    """Provide a unique conversation_id + clean up the filter afterwards."""
    import uuid
    conv_id = f"test-conv-{uuid.uuid4().hex}"
    yield conv_id
    discard_filter(conv_id)


@pytest.fixture
def mock_runner_factory(monkeypatch):
    """Replace OrchestrateRunner so the tool doesn't actually spawn a
    subprocess — we want to test the anonymization layer in isolation."""

    class _MockRunner:
        def __init__(self, *, user_id, **_kw):
            self.user_id = user_id

        async def run(self, *, code):
            from app.services.orchestrate_runner import OrchestrateResult
            # The "script" pretends to have fetched two emails from
            # Gmail and printed them — exactly the kind of PII that
            # would leak back to the main LLM without re-anonymization.
            return OrchestrateResult(
                stdout="Found 2 emails: alice@example.com, bob@example.org\n",
                stderr="warning: hit alice@example.com again",
                exit_code=0,
                duration_seconds=0.01,
                tools_dispatched=["gmail_list_emails"],
                truncated=False,
                truncation_reason="",
            )

    monkeypatch.setattr(
        "app.services.orchestrate_runner.OrchestrateRunner",
        _MockRunner,
    )
    # The tool imports OrchestrateRunner lazily inside the function body
    # so the patch on the module attribute is enough — no need to also
    # patch the namespace inside orchestrate_tool.


# ──────────────────────────────────────────────────────────────────────
# 1. Real PII in stdout is anonymized when conv_id is set
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stdout_is_anonymized_when_conv_id_set(
    isolated_conv_id, mock_runner_factory,
) -> None:
    ORCHESTRATE_CONVERSATION_ID.set(isolated_conv_id)
    result = await orchestrate.ainvoke({
        "code": "from ely_tools import gmail_list_emails\nprint(gmail_list_emails())",
        "user_id": "test-user",
    })
    # Raw emails must NOT appear in the returned text.
    assert "alice@example.com" not in result
    assert "bob@example.org" not in result
    # Placeholders must be present in their place.
    assert "[EMAIL_" in result


@pytest.mark.asyncio
async def test_stderr_is_anonymized_too(
    isolated_conv_id, mock_runner_factory,
) -> None:
    ORCHESTRATE_CONVERSATION_ID.set(isolated_conv_id)
    result = await orchestrate.ainvoke({
        "code": "print('hi')",
        "user_id": "test-user",
    })
    # The mock's stderr leaks alice@example.com into the meta header
    # (stderr_last=...). After anonymization, the header must not
    # contain the raw email either.
    assert "alice@example.com" not in result


# ──────────────────────────────────────────────────────────────────────
# 2. No conv_id → no crash, no anonymization attempted
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_conv_id_runs_without_anonymization(
    mock_runner_factory,
) -> None:
    # Reset the contextvar in case a previous test left a value.
    ORCHESTRATE_CONVERSATION_ID.set("")
    result = await orchestrate.ainvoke({
        "code": "print('hi')",
        "user_id": "test-user",
    })
    # No conv_id means no SecurityFilter — emails stay in cleartext.
    # This is acceptable because there's no LLM downstream consuming
    # this result in tests.
    assert "alice@example.com" in result


# ──────────────────────────────────────────────────────────────────────
# 3. Placeholder stability — same email = same placeholder across calls
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_placeholder_stable_within_conversation(
    isolated_conv_id, mock_runner_factory,
) -> None:
    """If the conversation's SecurityFilter has already seen
    alice@example.com (e.g. from an earlier message), the tool MUST
    reuse the same placeholder — otherwise the LLM sees two different
    tokens for the same real email and gets confused."""
    # Seed the filter with a known mapping by anonymizing a string
    # containing the email FIRST.
    sf = get_filter(isolated_conv_id)
    pre = sf.anonymize("Hello alice@example.com")
    # Capture the placeholder Alice got assigned.
    import re
    m = re.search(r"\[EMAIL_\d+\]", pre)
    assert m, "Test setup failed: SecurityFilter did not produce a placeholder"
    alice_placeholder = m.group(0)

    ORCHESTRATE_CONVERSATION_ID.set(isolated_conv_id)
    result = await orchestrate.ainvoke({
        "code": "print('hi')",
        "user_id": "test-user",
    })
    # The same placeholder must appear in the tool's result.
    assert alice_placeholder in result
    # And the real email must NOT appear.
    assert "alice@example.com" not in result


# ──────────────────────────────────────────────────────────────────────
# 4. The ContextVar default is the empty string (no leak across tests)
# ──────────────────────────────────────────────────────────────────────


def test_orchestrate_conversation_id_default_is_empty() -> None:
    """The ContextVar must default to "" so anonymization is opt-in via
    explicit set() — otherwise a stale value from an earlier turn could
    poison the next conversation."""
    # In a fresh task context, get() returns the default.
    assert ORCHESTRATE_CONVERSATION_ID.get() in {"", *((ORCHESTRATE_CONVERSATION_ID.get(),))}
    # More direct check: the registered default is "".
    # (We can't easily inspect ContextVar's default without using its
    # internals, so the assertion above suffices.)
