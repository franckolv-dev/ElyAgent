# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_conversation_truncate.py
# @brief      Jalon 4 — DELETE .../messages/from-last-user (retry & édition)
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the 'delete from last user message' endpoint that powers
retry/regenerate and edit-and-resend."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.database import async_session, init_db
from app.models.conversation import Conversation, Message


def _fake_user(uid: str):
    class _U:
        id = uid
    return _U()


_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _setup(uid: str, msgs: list[tuple[str, str]]) -> str:
    from app.models.user import User
    await init_db()
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-6:]}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        conv = Conversation(user_id=uid, title="t")
        db.add(conv)
        await db.flush()
        cid = str(conv.id)
        for i, (role, content) in enumerate(msgs):
            db.add(Message(
                conversation_id=cid, role=role, content=content,
                created_at=_BASE + timedelta(seconds=i),  # deterministic order
            ))
        await db.commit()
    return cid


async def _remaining(cid: str) -> list[str]:
    async with async_session() as db:
        rows = (await db.execute(
            select(Message).where(Message.conversation_id == cid)
            .order_by(Message.created_at.asc())
        )).scalars().all()
    return [m.content for m in rows]


async def _count(cid: str) -> int:
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Message)
            .where(Message.conversation_id == cid)
        )).scalar_one()


@pytest.mark.asyncio
async def test_truncate_removes_last_turn():
    from app.routers.conversations import delete_from_last_user
    uid = "tr_" + uuid.uuid4().hex[:8]
    cid = await _setup(uid, [
        ("user", "q1"), ("assistant", "a1"),
        ("user", "q2"), ("assistant", "a2"),
    ])
    out = await delete_from_last_user(cid, current_user=_fake_user(uid))
    assert out["deleted"] == 2
    assert await _remaining(cid) == ["q1", "a1"]  # only the last turn removed


@pytest.mark.asyncio
async def test_truncate_only_user_no_reply():
    """Last user message with no assistant reply yet → just that one removed."""
    from app.routers.conversations import delete_from_last_user
    uid = "tr_" + uuid.uuid4().hex[:8]
    cid = await _setup(uid, [("user", "q1"), ("assistant", "a1"), ("user", "q2")])
    out = await delete_from_last_user(cid, current_user=_fake_user(uid))
    assert out["deleted"] == 1
    assert await _remaining(cid) == ["q1", "a1"]


@pytest.mark.asyncio
async def test_truncate_ownership_is_404():
    from fastapi import HTTPException
    from app.routers.conversations import delete_from_last_user
    uid = "tr_" + uuid.uuid4().hex[:8]
    cid = await _setup(uid, [("user", "q1"), ("assistant", "a1")])
    with pytest.raises(HTTPException) as exc:
        await delete_from_last_user(cid, current_user=_fake_user("intruder"))
    assert exc.value.status_code == 404
    assert await _count(cid) == 2  # untouched


@pytest.mark.asyncio
async def test_truncate_no_user_message():
    from app.routers.conversations import delete_from_last_user
    uid = "tr_" + uuid.uuid4().hex[:8]
    cid = await _setup(uid, [("assistant", "a1")])
    out = await delete_from_last_user(cid, current_user=_fake_user(uid))
    assert out["deleted"] == 0
    assert await _count(cid) == 1
