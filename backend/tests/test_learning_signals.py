# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learning_signals.py
# @brief      Sprint 3.7 Jalon 2 — tests for the learning signals service
#             (record_hitl_refusal, record_hallucination_block,
#             record_tool_error, record_provider_switch) + verify the 4
#             call sites are actually wired in nodes.py / chat.py.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for app/services/learning/signals.py — Sprint 3.7 Jalon 2.

Two layers :
  1. Unit tests of the 4 record_* functions against an in-memory SQLite
     (no LLM, no Qdrant). Pins the row shape and the never-raise contract.
  2. Source-level wiring guards on nodes.py and chat.py so a future
     refactor that drops a record_* call fails the suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import async_session, init_db
from app.services.learning import (
    record_hallucination_block,
    record_hitl_refusal,
    record_provider_switch,
    record_tool_error,
)
from app.services.learning.signals import (
    MAX_VALUE_CHARS,
    _scrub_args,
)


@pytest_asyncio.fixture
async def _seeded_user():
    """Insert a user_id='u1' so the FK constraints on the signal tables
    don't reject our test rows. Idempotent — re-runs are safe."""
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.id == "u1"))).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="u1",
                username="learning_signals_test_user",
                email="u1@test.local",
                hashed_password="x",
            ))
            await db.commit()
    yield "u1"


# ── _scrub_args helper ────────────────────────────────────────────────


def test_scrub_args_truncates_long_string_values() -> None:
    long_text = "x" * 1000
    out = _scrub_args({"body": long_text})
    assert len(out["body"]) <= MAX_VALUE_CHARS + 1  # +1 for "…"
    assert out["body"].endswith("…")


def test_scrub_args_passes_short_strings_unchanged() -> None:
    out = _scrub_args({"q": "hello"})
    assert out == {"q": "hello"}


def test_scrub_args_keeps_primitives_intact() -> None:
    out = _scrub_args({"n": 42, "x": 3.14, "flag": True, "none": None})
    assert out == {"n": 42, "x": 3.14, "flag": True, "none": None}


def test_scrub_args_serializes_nested_collections() -> None:
    out = _scrub_args({"items": [1, 2, 3]})
    assert isinstance(out["items"], str)
    assert "[1, 2, 3]" in out["items"]


def test_scrub_args_handles_none_input() -> None:
    assert _scrub_args(None) == {}
    assert _scrub_args({}) == {}


# ── record_hitl_refusal ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_hitl_refusal_persists_row(_seeded_user) -> None:
    from app.models.hitl_refusal import HitlRefusal

    row_id = await record_hitl_refusal(
        user_id="u1",
        conversation_id="c1",
        tool_name="gmail_trash_emails",
        args={"query": "newsletter"},
        action_description="Trash 12 emails",
        decision="deny",
        reason="user-provided",
    )
    assert row_id is not None

    async with async_session() as db:
        rows = (await db.execute(select(HitlRefusal).where(HitlRefusal.id == row_id))).scalars().all()
        assert len(rows) == 1
        r = rows[0]
        assert r.user_id == "u1"
        assert r.tool_name == "gmail_trash_emails"
        assert r.decision == "deny"
        assert r.reason == "user-provided"
        # prompt_version auto-populated from current_system_prompt_version
        assert r.prompt_version is not None
        assert len(r.prompt_version) == 8
        # args were JSON-encoded with scrubbing
        parsed = json.loads(r.args_redacted)
        assert parsed == {"query": "newsletter"}


@pytest.mark.asyncio
async def test_record_hitl_refusal_returns_none_when_user_id_missing() -> None:
    row_id = await record_hitl_refusal(
        user_id="",
        conversation_id="c1",
        tool_name="x",
        args={},
        action_description="x",
        decision="deny",
        reason="x",
    )
    assert row_id is None


@pytest.mark.asyncio
async def test_record_hitl_refusal_never_raises_on_db_error(monkeypatch) -> None:
    """If async_session somehow blows up, the function must swallow."""
    from app.services.learning import signals as sig_mod

    class _BadSession:
        async def __aenter__(self): raise RuntimeError("db down")
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(sig_mod, "async_session", lambda: _BadSession())
    out = await record_hitl_refusal(
        user_id="u1", conversation_id="c1", tool_name="x",
        args={}, action_description="x", decision="deny", reason="x",
    )
    assert out is None  # swallowed, no exception


# ── record_hallucination_block ────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_hallucination_block_persists_with_payload(_seeded_user) -> None:
    from app.models.hallucination_block import HallucinationBlock

    row_id = await record_hallucination_block(
        user_id="u1",
        conversation_id="c1",
        model_used="gemma-4-e4b-it",
        matched_patterns=["fr.passive_past", "fr.quantified_done"],
        tools_invoked=[],
        destructive_tools_invoked=[],
        reason="completion_claim_without_destructive_tool_call",
        original_response="J'ai supprimé les 12 messages.",
    )
    assert row_id is not None

    async with async_session() as db:
        r = (await db.execute(
            select(HallucinationBlock).where(HallucinationBlock.id == row_id)
        )).scalar_one()
        assert r.user_id == "u1"
        assert r.tier_llm is None  # tier omitted at call site
        # JSON-encoded lists round-trip
        assert json.loads(r.matched_patterns) == ["fr.passive_past", "fr.quantified_done"]
        assert json.loads(r.tools_invoked) == []


# ── record_tool_error ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_tool_error_persists_with_full_payload(_seeded_user) -> None:
    from app.models.error_log import ErrorLog

    row_id = await record_tool_error(
        user_id="u1",
        tool_name="drive_find_duplicates",
        args={"folder_id": "abc"},
        error_type="HttpError",
        error_msg="Quota exceeded",
        traceback="Traceback (most recent call last)...",
        tier_llm="C",
    )
    assert row_id is not None

    async with async_session() as db:
        r = (await db.execute(
            select(ErrorLog).where(ErrorLog.id == row_id)
        )).scalar_one()
        assert r.user_id == "u1"
        assert r.tool_name == "drive_find_duplicates"
        assert r.error_type == "HttpError"
        assert r.tier_llm == "C"
        assert r.prompt_version is not None  # auto-populated


@pytest.mark.asyncio
async def test_record_tool_error_returns_none_on_empty_user_id() -> None:
    row_id = await record_tool_error(
        user_id="",
        tool_name="x",
        args={},
        error_type="X",
        error_msg="x",
    )
    assert row_id is None


# ── record_provider_switch ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_provider_switch_persists(_seeded_user) -> None:
    from app.models.provider_switch import ProviderSwitch

    row_id = await record_provider_switch(
        user_id="u1",
        conversation_id="c1",
        tier_llm="C",
        from_provider="deepseek-v4-pro",
        to_provider="anthropic-sonnet",
        reason="timeout",
        position_in_chain=2,
    )
    assert row_id is not None

    async with async_session() as db:
        r = (await db.execute(
            select(ProviderSwitch).where(ProviderSwitch.id == row_id)
        )).scalar_one()
        assert r.tier_llm == "C"
        assert r.from_provider == "deepseek-v4-pro"
        assert r.to_provider == "anthropic-sonnet"
        assert r.reason == "timeout"
        assert r.position_in_chain == 2


# ── Wiring guards : the 4 record_* calls must appear in their call sites ─


_REPO = Path(__file__).resolve().parents[1]


def test_nodes_py_wires_record_hitl_refusal() -> None:
    # After the 2026-05-25 refactor (Phase 3), tool_node — and therefore
    # the HITL signal recording — lives in app/agent/tool_node.py.
    src = (_REPO / "app" / "agent" / "tool_node.py").read_text(encoding="utf-8")
    assert "record_hitl_refusal" in src, (
        "tool_node.py must call record_hitl_refusal in both the 'ban' and "
        "'deny' branches of the HITL handler."
    )
    # Both branches present
    assert src.count("record_hitl_refusal") >= 2


def test_nodes_py_wires_record_tool_error() -> None:
    # Same relocation as test_nodes_py_wires_record_hitl_refusal above.
    src = (_REPO / "app" / "agent" / "tool_node.py").read_text(encoding="utf-8")
    assert "record_tool_error" in src, (
        "tool_node.py must call record_tool_error inside the tool except block."
    )


def test_nodes_py_wires_record_provider_switch() -> None:
    src = (_REPO / "app" / "agent" / "nodes.py").read_text(encoding="utf-8")
    assert "record_provider_switch" in src, (
        "nodes.py must call record_provider_switch just after fb.try_activate (~ line 1648)."
    )


def test_chat_py_wires_record_hallucination_block() -> None:
    src = (_REPO / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    assert "record_hallucination_block" in src, (
        "chat.py must call record_hallucination_block when completion_guard "
        "verdict.is_hallucination (~ line 612)."
    )
