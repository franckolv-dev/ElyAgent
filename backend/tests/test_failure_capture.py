# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_failure_capture.py
# @brief      Sprint 4b Phase 1 — tests for failure_cases capture from signals
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `app/services/learning/failure_capture.py` — Sprint 4b Phase 1.

Two layers :
  1. Unit tests of the 3 capture functions (HITL / hallucination / mission
     critique). Pins the row shape, the never-raise contract, and the
     filter that drops high-quality honest mission critiques.
  2. Integration tests proving the capture hooks fire when
     `signals.record_*` succeeds — i.e. no signal commits without a
     matching failure_case row.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.services.learning.failure_capture import (
    SIGNAL_HALLUCINATION,
    SIGNAL_HITL_REFUSAL,
    SIGNAL_MISSION_CRITIQUE,
    _fingerprint,
    _truncate,
    capture_from_hallucination_block,
    capture_from_hitl_refusal,
    capture_from_mission_critique,
)


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.id == "fc1"))).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="fc1",
                username="failure_capture_test_user",
                email="fc1@test.local",
                hashed_password="x",
            ))
            await db.commit()
    yield "fc1"


# ─────────────────────────────────────────────────────────────────────────
# _truncate
# ─────────────────────────────────────────────────────────────────────────


def test_truncate_short_string_unchanged():
    assert _truncate("hello") == "hello"


def test_truncate_none_returns_empty_string():
    assert _truncate(None) == ""


def test_truncate_long_string_capped_with_ellipsis():
    huge = "x" * 5000
    out = _truncate(huge)
    assert len(out) <= 2001
    assert out.endswith("…")


# ─────────────────────────────────────────────────────────────────────────
# _fingerprint
# ─────────────────────────────────────────────────────────────────────────


def test_fingerprint_stable_for_identical_inputs():
    a = _fingerprint("hitl_refusals", "gmail_trash_emails", "deny")
    b = _fingerprint("hitl_refusals", "gmail_trash_emails", "deny")
    assert a == b
    assert len(a) == 16


def test_fingerprint_differs_for_different_tools():
    a = _fingerprint("hitl_refusals", "gmail_trash_emails", "deny")
    b = _fingerprint("hitl_refusals", "drive_delete_file", "deny")
    assert a != b


def test_fingerprint_case_insensitive_normalisation():
    """Same logical pattern via different casing/spacing → same fingerprint
    (clustering must not double-count "Gmail_Trash" vs "gmail_trash")."""
    a = _fingerprint("hitl_refusals", "  Gmail_Trash  ", "DENY")
    b = _fingerprint("hitl_refusals", "gmail_trash", "deny")
    assert a == b


def test_fingerprint_handles_none_parts():
    """A None component must not crash + must produce a stable hash."""
    a = _fingerprint("hitl_refusals", None, "deny")
    b = _fingerprint("hitl_refusals", None, "deny")
    assert a == b
    assert len(a) == 16


# ─────────────────────────────────────────────────────────────────────────
# capture_from_hitl_refusal
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_hitl_creates_row_with_expected_shape(_seeded_user):
    fc_id = await capture_from_hitl_refusal(
        signal_id=1,
        user_id=_seeded_user,
        conversation_id="conv1",
        tool_name="gmail_trash_emails",
        args_redacted='{"query":"from:shein"}',
        action_description="Move 12 emails to trash",
        decision="deny",
        reason="user-provided",
        tier_llm="B",
        prompt_version="abc12345",
    )
    assert fc_id is not None
    async with async_session() as db:
        row = (await db.execute(
            select(FailureCase).where(FailureCase.id == fc_id)
        )).scalar_one()
    assert row.signal_table == SIGNAL_HITL_REFUSAL
    assert row.signal_id == 1
    assert row.conversation_id == "conv1"
    assert row.tier_llm == "B"
    assert row.prompt_version == "abc12345"
    assert row.processed_at is None  # still pending for the skill_creator
    assert row.pattern_hash is not None
    payload = json.loads(row.replay_payload)
    assert payload["signal_kind"] == "hitl_refusal"
    assert payload["tool_name"] == "gmail_trash_emails"
    assert payload["decision"] == "deny"


@pytest.mark.asyncio
async def test_capture_hitl_returns_none_when_no_user(_seeded_user):
    out = await capture_from_hitl_refusal(
        signal_id=2,
        user_id="",
        conversation_id="conv1",
        tool_name="x",
        args_redacted="{}",
        action_description="d",
        decision="deny",
        reason="x",
    )
    assert out is None


# ─────────────────────────────────────────────────────────────────────────
# capture_from_hallucination_block
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_hallucination_creates_row(_seeded_user):
    fc_id = await capture_from_hallucination_block(
        signal_id=10,
        user_id=_seeded_user,
        conversation_id="conv2",
        model_used="deepseek-v4-flash",
        matched_patterns=["j'ai supprimé"],
        tools_invoked=["gmail_list_emails"],
        destructive_tools_invoked=[],
        reason="claim without destructive tool",
        original_response="J'ai supprimé tous les emails AliExpress",
        tier_llm="B",
    )
    assert fc_id is not None
    async with async_session() as db:
        row = (await db.execute(
            select(FailureCase).where(FailureCase.id == fc_id)
        )).scalar_one()
    assert row.signal_table == SIGNAL_HALLUCINATION
    payload = json.loads(row.replay_payload)
    assert payload["model_used"] == "deepseek-v4-flash"
    assert payload["matched_patterns"] == ["j'ai supprimé"]
    assert payload["destructive_tools_invoked"] == []
    # Sanity: capping at MAX_FIELD_CHARS works on a huge response
    assert len(payload["original_response"]) <= 2001


@pytest.mark.asyncio
async def test_capture_hallucination_caps_huge_response(_seeded_user):
    huge = "A" * 10000
    fc_id = await capture_from_hallucination_block(
        signal_id=11,
        user_id=_seeded_user,
        conversation_id="conv2b",
        model_used="m",
        matched_patterns=["p"],
        tools_invoked=[],
        destructive_tools_invoked=[],
        reason="r",
        original_response=huge,
    )
    assert fc_id is not None
    async with async_session() as db:
        row = (await db.execute(
            select(FailureCase).where(FailureCase.id == fc_id)
        )).scalar_one()
    payload = json.loads(row.replay_payload)
    assert payload["original_response"].endswith("…")
    assert len(payload["original_response"]) <= 2001


# ─────────────────────────────────────────────────────────────────────────
# capture_from_mission_critique
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_mission_critique_low_score_creates_row(_seeded_user):
    fc_id = await capture_from_mission_critique(
        signal_id=20,
        user_id=_seeded_user,
        mission_id="mis_low",
        critic_model="deepseek-v4-pro",
        quality_score=30,
        honest_completion=True,
        wasted_effort=True,
        user_should_have_been_warned=False,
        main_issue="too many retries on drive_list_files",
    )
    assert fc_id is not None
    async with async_session() as db:
        row = (await db.execute(
            select(FailureCase).where(FailureCase.id == fc_id)
        )).scalar_one()
    assert row.signal_table == SIGNAL_MISSION_CRITIQUE
    payload = json.loads(row.replay_payload)
    assert payload["quality_score"] == 30
    assert payload["main_issue"].startswith("too many retries")


@pytest.mark.asyncio
async def test_capture_mission_critique_high_score_honest_is_skipped(_seeded_user):
    """A high-quality honest mission must NOT create a failure_case —
    no point asking the skill_creator to fix what's already working."""
    fc_id = await capture_from_mission_critique(
        signal_id=21,
        user_id=_seeded_user,
        mission_id="mis_good",
        critic_model="deepseek-v4-pro",
        quality_score=92,
        honest_completion=True,
        wasted_effort=False,
        user_should_have_been_warned=False,
        main_issue=None,
    )
    assert fc_id is None  # filtered out


@pytest.mark.asyncio
async def test_capture_mission_critique_dishonest_high_score_is_captured(_seeded_user):
    """A dishonest mission (agent claimed success but lied) is captured
    even with a 'high' score — the dishonesty itself is the failure."""
    fc_id = await capture_from_mission_critique(
        signal_id=22,
        user_id=_seeded_user,
        mission_id="mis_dishonest",
        critic_model="deepseek-v4-pro",
        quality_score=85,
        honest_completion=False,   # ← the trigger
        wasted_effort=False,
        user_should_have_been_warned=True,
        main_issue="claimed file uploaded but no drive_create_file call",
    )
    assert fc_id is not None


# ─────────────────────────────────────────────────────────────────────────
# Wire-up integration : signals.record_* triggers failure_capture
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_hitl_refusal_creates_matching_failure_case(_seeded_user):
    """End-to-end: record_hitl_refusal must persist BOTH the hitl_refusals
    row AND a matching failure_cases row."""
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning import record_hitl_refusal

    signal_id = await record_hitl_refusal(
        user_id=_seeded_user,
        conversation_id="convW",
        tool_name="gmail_trash_emails",
        args=None,
        action_description="Move 5 emails to trash",
        decision="deny",
        reason="user-provided",
    )
    assert signal_id is not None

    async with async_session() as db:
        # Signal row
        sig = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.id == signal_id)
        )).scalar_one()
        assert sig.tool_name == "gmail_trash_emails"

        # Matching failure_case row. Filter by user_id too — other tests
        # in the same suite (test_skill_creator) seed FailureCase rows
        # with random signal_ids that can occasionally collide with
        # the autoincrement id assigned to our HitlRefusal in CI's
        # accumulated DB. Without the user_id filter we hit
        # MultipleResultsFound in CI even though local runs pass.
        fc = (await db.execute(
            select(FailureCase).where(
                FailureCase.signal_table == SIGNAL_HITL_REFUSAL,
                FailureCase.signal_id == signal_id,
                FailureCase.user_id == _seeded_user,
            )
        )).scalar_one_or_none()
        assert fc is not None, "record_hitl_refusal must create a failure_case row"


@pytest.mark.asyncio
async def test_record_hallucination_creates_matching_failure_case(_seeded_user):
    from app.models.hallucination_block import HallucinationBlock
    from app.services.learning import record_hallucination_block

    signal_id = await record_hallucination_block(
        user_id=_seeded_user,
        conversation_id="convX",
        model_used="m",
        matched_patterns=["j'ai envoyé"],
        tools_invoked=[],
        destructive_tools_invoked=[],
        reason="r",
        original_response="J'ai envoyé l'email à Alice.",
    )
    assert signal_id is not None

    async with async_session() as db:
        sig = (await db.execute(
            select(HallucinationBlock).where(HallucinationBlock.id == signal_id)
        )).scalar_one()
        assert sig is not None
        # Same user_id filter rationale as the HITL test above.
        fc = (await db.execute(
            select(FailureCase).where(
                FailureCase.signal_table == SIGNAL_HALLUCINATION,
                FailureCase.signal_id == signal_id,
                FailureCase.user_id == _seeded_user,
            )
        )).scalar_one_or_none()
        assert fc is not None


# ─────────────────────────────────────────────────────────────────────────
# Never-raise contract
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_never_raises_on_db_error(monkeypatch, _seeded_user):
    """Even if the underlying DB session blows up, the capture function
    must swallow the exception and return None."""
    from app.services.learning import failure_capture as fc_mod

    class _BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("simulated DB outage")
        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(fc_mod, "async_session", lambda: _BrokenSession())

    out = await capture_from_hitl_refusal(
        signal_id=99,
        user_id=_seeded_user,
        conversation_id="conv-broken",
        tool_name="any",
        args_redacted="{}",
        action_description="d",
        decision="deny",
        reason="x",
    )
    assert out is None  # swallowed, no exception bubbled
