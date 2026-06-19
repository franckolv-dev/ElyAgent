# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_overridable.py
# @brief      HITL : outils dangereux désactivables + timeout ≠ refus + délai.
# =============================================================================
"""Tests des évolutions HITL (demande Franck 2026-06-19) :
- les outils dangereux (ex-verrouillés) honorent désormais la préférence user
  → « Autoriser définitivement » persiste ;
- un timeout n'est plus enregistré comme un refus délibéré ;
- le délai de validation est configurable.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.hitl_preference import HitlPreference
from app.models.hitl_refusal import HitlRefusal
from app.services.hitl_preferences import (
    LOCKED_HITL_TOOLS,
    set_user_preference,
    user_requires_hitl,
)
from app.services.learning.signals import record_hitl_refusal

# Un outil DANGEREUX (ex-verrouillé) + un outil critique régulier.
_DANGEROUS = "gmail_trash_emails"


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "hitl_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(HitlPreference).where(HitlPreference.user_id == uid))
        await db.execute(delete(HitlRefusal).where(HitlRefusal.user_id == uid))
        await db.commit()


# ── Outils dangereux : ON par défaut mais désactivables ──────────────────────
@pytest.mark.asyncio
async def test_dangerous_tool_default_is_hitl_on(_user):
    assert _DANGEROUS in LOCKED_HITL_TOOLS
    # aucune préférence → confirmation requise (défaut sûr)
    assert await user_requires_hitl(_user, _DANGEROUS) is True


@pytest.mark.asyncio
async def test_dangerous_tool_pref_now_honored(_user):
    # « Autoriser définitivement » / toggle DANGEREUX écrit requires_confirmation=False
    assert await set_user_preference(_user, _DANGEROUS, requires_confirmation=False) is True
    # ← LE FIX : avant, un outil verrouillé renvoyait True en dur
    assert await user_requires_hitl(_user, _DANGEROUS) is False


@pytest.mark.asyncio
async def test_dangerous_tool_can_be_re_enabled(_user):
    await set_user_preference(_user, _DANGEROUS, requires_confirmation=False)
    await set_user_preference(_user, _DANGEROUS, requires_confirmation=True)
    assert await user_requires_hitl(_user, _DANGEROUS) is True


@pytest.mark.asyncio
async def test_empty_user_defaults_true():
    assert await user_requires_hitl("", _DANGEROUS) is True


# ── Timeout ≠ refus délibéré ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_timeout_not_recorded_as_refusal(_user):
    n = await record_hitl_refusal(
        user_id=_user, conversation_id="conv-x", tool_name=_DANGEROUS,
        args={}, action_description="trash", decision="deny", reason="timeout",
    )
    assert n is None
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.user_id == _user)
        )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_deliberate_deny_is_still_recorded(_user):
    n = await record_hitl_refusal(
        user_id=_user, conversation_id="conv-x", tool_name=_DANGEROUS,
        args={}, action_description="trash", decision="deny", reason="user-provided",
    )
    assert n is not None
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.user_id == _user)
        )).scalars().all()
    assert len(rows) == 1


# ── Délai configurable ───────────────────────────────────────────────────────
def test_timeout_seconds_reads_config(monkeypatch):
    from app.services import hitl_manager
    # défaut = 30 min
    assert hitl_manager._timeout_seconds() == 1800
    # surcharge via settings
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "hitl_timeout_seconds", 900, raising=False)
    monkeypatch.setattr(hitl_manager, "get_settings", lambda: s)
    assert hitl_manager._timeout_seconds() == 900
