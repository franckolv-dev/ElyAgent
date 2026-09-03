# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_io_tool_audit.py
# @brief      Sprint 4b V3 J6.c.1 — IoToolDispatch model + record_dispatch service.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins:

  1. ``record_dispatch`` writes the row with the snapshot shape we
     expect (secrets are LABELS not values, durations rounded to ms,
     long errors truncated to 500 chars).
  2. ``record_dispatch`` NEVER raises — a DB hiccup logs and swallows so
     the caller (the dispatcher) is not blocked on us.
  3. Roundtrip: a new IoToolDispatch persists and re-reads through
     SQLAlchemy unchanged.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.io_tool_dispatch import IoToolDispatch
from app.services.learning.io_tool_audit import record_dispatch


# ── Seeded user, isolated rows ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def _audit_user():
    await init_db()
    from app.models.user import User
    user_id = "audit_user"
    async with async_session() as db:
        existing = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id=user_id,
                username="audit_test_user",
                email=f"{user_id}@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(
            delete(IoToolDispatch).where(IoToolDispatch.user_id == user_id)
        )
        await db.commit()
    yield user_id
    async with async_session() as db:
        await db.execute(
            delete(IoToolDispatch).where(IoToolDispatch.user_id == user_id)
        )
        await db.commit()


# ── Roundtrip ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_dispatch_writes_row_with_snapshot_shape(_audit_user):
    """Pin the canonical shape: secrets = LABELS, network_allow snapshotted,
    duration rounded to ms, outcome echoed."""
    await record_dispatch(
        user_id=_audit_user,
        skill_id="skill-abc-123",
        tool_name="weather_probe",
        outcome="returned",
        duration_s=0.4567,
        secrets_used=("openweather_api_key",),
        network_allow=(".openweathermap.org",),
        conversation_id="conv-42",
    )

    async with async_session() as db:
        row = (await db.execute(
            select(IoToolDispatch).where(IoToolDispatch.user_id == _audit_user)
        )).scalar_one()

    assert row.skill_id == "skill-abc-123"
    assert row.tool_name == "weather_probe"
    assert row.outcome == "returned"
    assert row.duration_ms == 457  # 0.4567 → 457 ms (banker's rounding OK)
    assert json.loads(row.secrets_used_json) == ["openweather_api_key"]
    assert json.loads(row.network_allow_json) == [".openweathermap.org"]
    assert row.error_truncated is None
    assert row.conversation_id == "conv-42"


@pytest.mark.asyncio
async def test_record_dispatch_truncates_error_to_500_chars(_audit_user):
    """A pathological error message (eg. a huge traceback that slipped
    through formatting) must not blow the column width."""
    huge_error = "x" * 5000
    await record_dispatch(
        user_id=_audit_user,
        skill_id="skill-xxx",
        tool_name="bad_tool",
        outcome="raised",
        error=huge_error,
    )

    async with async_session() as db:
        row = (await db.execute(
            select(IoToolDispatch).where(IoToolDispatch.user_id == _audit_user)
        )).scalar_one()

    assert row.error_truncated is not None
    assert len(row.error_truncated) == 500


@pytest.mark.asyncio
async def test_record_dispatch_caps_tool_name_and_outcome(_audit_user):
    """A pathological-but-bounded input (a future outcome string longer than
    24 chars; a tool name longer than 64 chars) must NOT raise — we cap."""
    await record_dispatch(
        user_id=_audit_user,
        skill_id="skill-y",
        tool_name="a_very_long_tool_name_" + "x" * 200,
        outcome="this_outcome_is_too_long_for_the_column_width",
    )

    async with async_session() as db:
        row = (await db.execute(
            select(IoToolDispatch).where(IoToolDispatch.user_id == _audit_user)
        )).scalar_one()
    assert len(row.tool_name) <= 64
    assert len(row.outcome) <= 24


@pytest.mark.asyncio
async def test_record_dispatch_empty_secrets_and_network_stored_as_empty_arrays(_audit_user):
    """A no-secret no-domain io tool (eg. a pure-compute V3 tool that just
    needs the sandbox isolation) gets `[]` not null — pin the contract."""
    await record_dispatch(
        user_id=_audit_user,
        skill_id="skill-z",
        tool_name="trivial",
        outcome="returned",
    )

    async with async_session() as db:
        row = (await db.execute(
            select(IoToolDispatch).where(IoToolDispatch.user_id == _audit_user)
        )).scalar_one()
    assert row.secrets_used_json == "[]"
    assert row.network_allow_json == "[]"


# ── Best-effort: never raises ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_dispatch_does_not_raise_on_unknown_user(caplog):
    """The FK on user_id is `users.id`. Passing an unknown user MUST be
    swallowed (warning log) — the caller is the dispatcher, whose LLM
    has already seen the result. A DB hiccup must not retroactively
    break the conversation."""
    with caplog.at_level("WARNING"):
        # Should not raise.
        await record_dispatch(
            user_id="<<does not exist>>",
            skill_id="skill-x",
            tool_name="ghost",
            outcome="returned",
        )
    # The function logged the swallow (best-effort contract).
    assert any(
        "record_dispatch failed" in record.message
        for record in caplog.records
    ), f"expected a 'record_dispatch failed' warning in {caplog.records}"
