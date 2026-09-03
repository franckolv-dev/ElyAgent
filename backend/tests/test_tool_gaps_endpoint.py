# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_gaps_endpoint.py
# @brief      Admin /tool-gaps endpoints — list + mark-processed.
# @license    MIT
# =============================================================================
"""find_tool Phase 2 records `tool_absent` gaps as FailureCase rows; this
endpoint surfaces them for HITL review."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.services.learning.failure_capture import record_tool_absent


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"tg-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"tg_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(FailureCase).where(FailureCase.user_id == uid))
        await db.execute(delete(__import__("app.models.user", fromlist=["User"]).User).where(
            __import__("app.models.user", fromlist=["User"]).User.id == uid
        ))
        await db.commit()


# ── GET /tool-gaps ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tool_gaps_filters_open_by_default(_user):
    """Only `signal_table='tool_absent'` rows with processed_at NULL by default."""
    # Seed: 2 open gaps + 1 processed gap (for this user) + 1 unrelated signal.
    await record_tool_absent(user_id=_user, capability="lire un Google Sheet existant")
    await record_tool_absent(user_id=_user, capability="poster sur Slack")
    async with async_session() as db:
        # Mark one as processed
        gap = (await db.execute(
            select(FailureCase).where(FailureCase.user_id == _user).limit(1)
        )).scalar_one()
        from datetime import datetime, timezone
        gap.processed_at = datetime.now(timezone.utc)
        # Add an unrelated failure_case to make sure the signal_table filter holds
        db.add(FailureCase(
            user_id=_user, signal_table="hitl_refusal", signal_id=1,
            replay_payload="{}", expected_outcome="something else",
        ))
        await db.commit()

    from app.routers.learning_skills import list_tool_gaps

    async with async_session() as db:
        out = await list_tool_gaps(
            status="open", user_id=_user, limit=100, _admin=None, db=db,
        )
    # Only the one still-unprocessed tool_absent row, not the hitl_refusal.
    assert len(out) == 1
    assert out[0].capability == "poster sur Slack"
    assert out[0].processed_at is None


@pytest.mark.asyncio
async def test_list_tool_gaps_status_all_includes_processed(_user):
    await record_tool_absent(user_id=_user, capability="lire un Google Sheet existant")
    await record_tool_absent(user_id=_user, capability="poster sur Slack")
    async with async_session() as db:
        gap = (await db.execute(
            select(FailureCase).where(FailureCase.user_id == _user).limit(1)
        )).scalar_one()
        from datetime import datetime, timezone
        gap.processed_at = datetime.now(timezone.utc)
        await db.commit()

    from app.routers.learning_skills import list_tool_gaps

    async with async_session() as db:
        out = await list_tool_gaps(
            status="all", user_id=_user, limit=100, _admin=None, db=db,
        )
    assert len(out) == 2
    statuses = sorted(g.processed_at is None for g in out)
    assert statuses == [False, True]


@pytest.mark.asyncio
async def test_list_tool_gaps_extracts_capability_from_payload(_user):
    """Capability comes from replay_payload JSON (richer than expected_outcome)."""
    await record_tool_absent(user_id=_user, capability="composer une animation 3D")
    from app.routers.learning_skills import list_tool_gaps

    async with async_session() as db:
        out = await list_tool_gaps(
            status="open", user_id=_user, limit=100, _admin=None, db=db,
        )
    assert len(out) == 1
    assert out[0].capability == "composer une animation 3D"


@pytest.mark.asyncio
async def test_list_tool_gaps_capability_falls_back_when_payload_broken(_user):
    """If the payload JSON is malformed, fall back to expected_outcome."""
    async with async_session() as db:
        db.add(FailureCase(
            user_id=_user, signal_table="tool_absent", signal_id=0,
            replay_payload="not-json{",  # malformed
            expected_outcome="capability-from-column",
        ))
        await db.commit()

    from app.routers.learning_skills import list_tool_gaps

    async with async_session() as db:
        out = await list_tool_gaps(
            status="open", user_id=_user, limit=100, _admin=None, db=db,
        )
    assert len(out) == 1
    assert out[0].capability == "capability-from-column"


@pytest.mark.asyncio
async def test_list_tool_gaps_rejects_invalid_status(_user):
    from fastapi import HTTPException

    from app.routers.learning_skills import list_tool_gaps

    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await list_tool_gaps(
                status="bogus", user_id=_user, limit=100, _admin=None, db=db,
            )
    assert exc.value.status_code == 400


# ── POST /tool-gaps/{id}/mark-processed ──────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_processed_sets_timestamp_and_skill_id(_user):
    gap_id = await record_tool_absent(user_id=_user, capability="poster sur Slack")
    assert gap_id is not None

    # Create a real LearnedSkill so the FK (failure_cases.learned_skill_id →
    # learned_skills.id) is satisfied.
    from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus

    skill_id = f"sk-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(LearnedSkill(
            id=skill_id, user_id=_user, name="poster-sur-slack",
            description="generated", content="# Playbook",
            status=SkillStatus.CANDIDATE, source=SkillSource.AUTO_GENERATED,
        ))
        await db.commit()

    from app.routers.learning_skills import (
        ToolGapMarkProcessedRequest,
        mark_tool_gap_processed,
    )
    from types import SimpleNamespace

    admin = SimpleNamespace(id="admin-1")
    async with async_session() as db:
        out = await mark_tool_gap_processed(
            gap_id=gap_id,
            body=ToolGapMarkProcessedRequest(learned_skill_id=skill_id),
            _admin=admin, db=db,
        )
    assert out.processed_at is not None
    assert out.learned_skill_id == skill_id

    # Cleanup the LearnedSkill (FailureCase will reference it but the row is
    # deleted by the _user fixture teardown anyway).
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.id == skill_id))
        await db.commit()


@pytest.mark.asyncio
async def test_mark_processed_is_idempotent(_user):
    gap_id = await record_tool_absent(user_id=_user, capability="poster sur Slack")
    from app.routers.learning_skills import mark_tool_gap_processed
    from types import SimpleNamespace

    admin = SimpleNamespace(id="admin-1")
    async with async_session() as db:
        first = await mark_tool_gap_processed(gap_id=gap_id, body=None, _admin=admin, db=db)
    async with async_session() as db:
        second = await mark_tool_gap_processed(gap_id=gap_id, body=None, _admin=admin, db=db)
    # Same processed_at timestamp on the second call (no clobber).
    assert first.processed_at == second.processed_at


@pytest.mark.asyncio
async def test_mark_processed_404_on_unknown_gap(_user):
    from fastapi import HTTPException

    from app.routers.learning_skills import mark_tool_gap_processed
    from types import SimpleNamespace

    admin = SimpleNamespace(id="admin-1")
    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await mark_tool_gap_processed(gap_id=999_999, body=None, _admin=admin, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_processed_rejects_non_tool_absent_signals(_user):
    """A row in failure_cases with a different signal_table must not be reachable here."""
    from fastapi import HTTPException

    async with async_session() as db:
        row = FailureCase(
            user_id=_user, signal_table="hitl_refusal", signal_id=1,
            replay_payload="{}", expected_outcome="not a tool_absent",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        unrelated_id = row.id

    from app.routers.learning_skills import mark_tool_gap_processed
    from types import SimpleNamespace

    admin = SimpleNamespace(id="admin-1")
    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await mark_tool_gap_processed(gap_id=unrelated_id, body=None, _admin=admin, db=db)
    assert exc.value.status_code == 404
