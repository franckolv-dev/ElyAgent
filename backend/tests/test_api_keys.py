# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_api_keys.py
# @brief      Clés API personnelles (serveur MCP J1) — helpers + résolveur auth.
# =============================================================================
"""Tests des clés API personnelles : format/hash des helpers + le résolveur
``authenticate_api_key`` (la brique de sécurité dont dépendra le serveur MCP).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database import async_session, init_db
from app.models.api_key import ApiKey
from app.routers.api_keys import (
    KEY_ENTROPY_BYTES,
    KEY_PREFIX,
    _generate_plaintext,
    authenticate_api_key,
    hash_key,
)


# ── Helpers purs ─────────────────────────────────────────────────────────────
def test_key_format():
    key = _generate_plaintext()
    assert key.startswith(KEY_PREFIX)
    body = key[len(KEY_PREFIX):]
    assert len(body) == KEY_ENTROPY_BYTES * 2  # token_hex(N) → 2N hex
    assert all(c in "0123456789abcdef" for c in body)


def test_keys_are_unique():
    assert len({_generate_plaintext() for _ in range(20)}) == 20


def test_hash_is_deterministic_and_hex():
    k = KEY_PREFIX + "a" * 64
    assert hash_key(k) == hash_key(k)
    assert len(hash_key(k)) == 64
    assert all(c in "0123456789abcdef" for c in hash_key(k))


def test_hash_differs_across_keys():
    assert hash_key(KEY_PREFIX + "a" * 64) != hash_key(KEY_PREFIX + "b" * 64)


# ── Résolveur authenticate_api_key (DB) ──────────────────────────────────────
@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "apikey_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(ApiKey).where(ApiKey.user_id == uid))
        await db.commit()


async def _mint(uid: str, plaintext: str, *, revoked: bool = False) -> None:
    async with async_session() as db:
        db.add(ApiKey(
            user_id=uid,
            name="test",
            key_hash=hash_key(plaintext),
            last_4=plaintext[-4:],
            created_at=datetime.utcnow(),
            revoked_at=datetime.utcnow() if revoked else None,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_valid_key_resolves_to_user(_user):
    plaintext = _generate_plaintext()
    await _mint(_user, plaintext)
    async with async_session() as db:
        user = await authenticate_api_key(plaintext, db)
    assert user is not None
    assert user.id == _user


@pytest.mark.asyncio
async def test_valid_key_stamps_last_used(_user):
    plaintext = _generate_plaintext()
    await _mint(_user, plaintext)
    async with async_session() as db:
        await authenticate_api_key(plaintext, db)
    async with async_session() as db:
        from sqlalchemy import select
        row = (await db.execute(
            select(ApiKey).where(ApiKey.key_hash == hash_key(plaintext))
        )).scalar_one()
    assert row.last_used_at is not None


@pytest.mark.asyncio
async def test_unknown_key_returns_none(_user):
    async with async_session() as db:
        assert await authenticate_api_key(_generate_plaintext(), db) is None


@pytest.mark.asyncio
async def test_revoked_key_returns_none(_user):
    plaintext = _generate_plaintext()
    await _mint(_user, plaintext, revoked=True)
    async with async_session() as db:
        assert await authenticate_api_key(plaintext, db) is None


@pytest.mark.asyncio
async def test_wrong_prefix_returns_none(_user):
    # Even if the hash happened to exist, a non-ely_api_ string is rejected early.
    async with async_session() as db:
        assert await authenticate_api_key("Bearer-ish-not-a-key", db) is None
        assert await authenticate_api_key("", db) is None
        assert await authenticate_api_key("ely_ext_" + "a" * 48, db) is None
