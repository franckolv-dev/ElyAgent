# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_user_state_wiring.py
# @brief      Sprint 3 Jalon 2 — pin the wiring contract :
#             - maintenance_rapid.consolidate calls _refresh_user_state
#             - _refresh_user_state invalidates frozen_memory
#             - USER_STATE_DISABLED kill-switch is honoured at call time
#             - exceptions in compute_user_state never escape the hook
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the Sprint 3 Jalon 2 wiring (maintenance hook + invalidation)."""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from app.services import frozen_memory as _fm
from app.services.learning import user_state as us
from app.services.memory.maintenance_rapid import MaintenanceAgentRapid


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fresh_user():
    """Create a throw-away user so the FK on user_states is satisfied."""
    from app.database import async_session, init_db
    from app.models.user import User
    from app.models.user_state import UserState
    from sqlalchemy import select

    await init_db()
    uid = f"test_us_w_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"usw_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    yield uid
    async with async_session() as db:
        row = (await db.execute(
            select(UserState).where(UserState.user_id == uid)
        )).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
        u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Reset USER_STATE_DISABLED between tests so a leak doesn't poison
    the next case."""
    monkeypatch.delenv("USER_STATE_DISABLED", raising=False)
    yield


# ─────────────────────────────────────────────────────────────────────────
# is_disabled() — kill-switch contract
# ─────────────────────────────────────────────────────────────────────────


def test_is_disabled_default_false() -> None:
    assert us.is_disabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "TRUE", "Yes"])
def test_is_disabled_honors_env(monkeypatch, val) -> None:
    monkeypatch.setenv("USER_STATE_DISABLED", val)
    assert us.is_disabled() is True


@pytest.mark.parametrize("val", ["0", "false", "", "off", "no"])
def test_is_disabled_falsy_values_keep_feature_on(monkeypatch, val) -> None:
    monkeypatch.setenv("USER_STATE_DISABLED", val)
    assert us.is_disabled() is False


def test_format_user_state_block_short_circuits_when_disabled(monkeypatch) -> None:
    """Block must be empty even with rich state when the kill-switch is on."""
    monkeypatch.setenv("USER_STATE_DISABLED", "1")
    assert us.format_user_state_block({
        **us.DEFAULT_STATE,
        "mood": "focused",
        "current_focus": "Sprint 3",
    }) == ""


# ─────────────────────────────────────────────────────────────────────────
# MaintenanceAgentRapid._refresh_user_state — wiring
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_user_state_calls_compute_and_invalidates(
    monkeypatch, fresh_user: str,
) -> None:
    """Happy path : compute_user_state runs, frozen_memory is invalidated."""
    agent = MaintenanceAgentRapid()
    conv_id = f"conv_us_{uuid.uuid4().hex[:6]}"

    # Pre-seed the frozen_memory cache so we can detect invalidation
    async def _builder() -> str:
        return "stub snapshot"

    await _fm.get_or_build(conv_id, fresh_user, _builder)
    assert conv_id in _fm._snapshots  # sanity

    # Spy on compute_user_state
    compute_calls = []

    async def fake_compute(user_id, conversation_id=None, **_kw):
        compute_calls.append((user_id, conversation_id))
        return us.DEFAULT_STATE

    monkeypatch.setattr(us, "compute_user_state", fake_compute)

    status = await agent._refresh_user_state(fresh_user, conv_id)
    assert status == "refreshed"
    assert compute_calls == [(fresh_user, conv_id)]
    assert conv_id not in _fm._snapshots  # invalidated


@pytest.mark.asyncio
async def test_refresh_user_state_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("USER_STATE_DISABLED", "1")
    agent = MaintenanceAgentRapid()

    called = []

    async def fake_compute(*args, **kwargs):
        called.append(args)
        return us.DEFAULT_STATE

    monkeypatch.setattr(us, "compute_user_state", fake_compute)
    status = await agent._refresh_user_state("u1", "c1")
    assert status == "skipped"
    assert called == []  # LLM was never invoked


@pytest.mark.asyncio
async def test_refresh_user_state_returns_failed_on_internal_exception(
    monkeypatch,
) -> None:
    """If compute_user_state explodes (it shouldn't, but be defensive),
    the hook returns 'failed' and the consolidate pipeline keeps going."""
    agent = MaintenanceAgentRapid()

    async def crashing_compute(*args, **kwargs):
        raise RuntimeError("forced explosion")

    monkeypatch.setattr(us, "compute_user_state", crashing_compute)
    status = await agent._refresh_user_state("u1", "c1")
    assert status == "failed"


@pytest.mark.asyncio
async def test_consolidate_returns_user_state_status_in_dict(
    monkeypatch, fresh_user: str,
) -> None:
    """The consolidate() return dict must surface the user_state status
    so an operator can see at a glance whether the refresh ran."""
    agent = MaintenanceAgentRapid()
    conv_id = f"conv_us_{uuid.uuid4().hex[:6]}"

    # Make _load_recent_messages return >= MIN_MESSAGES_TO_RUN entries
    async def fake_load(*_a, **_kw):
        return [
            type("M", (), {"role": "user", "content": "salut"})(),
            type("M", (), {"role": "assistant", "content": "hello"})(),
            type("M", (), {"role": "user", "content": "ok bye"})(),
        ]
    monkeypatch.setattr(agent, "_load_recent_messages", fake_load)

    # Stub the fact extractor to return nothing → exercises the no-facts
    # path which now also refreshes user_state.
    async def fake_extract(*_a, **_kw):
        return []
    monkeypatch.setattr(agent, "_extract_facts", fake_extract)

    # Stub compute_user_state to avoid the real LLM
    async def fake_compute(user_id, conversation_id=None, **_kw):
        return us.DEFAULT_STATE
    monkeypatch.setattr(us, "compute_user_state", fake_compute)

    result = await agent.consolidate(conv_id, fresh_user)
    assert result["status"] == "ok"
    assert result["user_state"] == "refreshed"
    assert result["facts"] == 0
    assert result["preferences"] == 0


@pytest.mark.asyncio
async def test_consolidate_with_facts_also_refreshes_state(
    monkeypatch, fresh_user: str,
) -> None:
    """The hook on the WITH-facts path must run too."""
    agent = MaintenanceAgentRapid()
    conv_id = f"conv_us_{uuid.uuid4().hex[:6]}"

    async def fake_load(*_a, **_kw):
        return [type("M", (), {"role": "user", "content": "x"})()] * 5
    monkeypatch.setattr(agent, "_load_recent_messages", fake_load)

    async def fake_extract(*_a, **_kw):
        return [{"fact": "user prefers French", "type": "preference"}]
    monkeypatch.setattr(agent, "_extract_facts", fake_extract)

    # Stub _store_facts so we don't actually hit Qdrant
    async def fake_store(*_a, **_kw):
        return (1, 0)
    monkeypatch.setattr(agent, "_store_facts", fake_store)

    state_calls = []

    async def fake_compute(user_id, conversation_id=None, **_kw):
        state_calls.append((user_id, conversation_id))
        return us.DEFAULT_STATE
    monkeypatch.setattr(us, "compute_user_state", fake_compute)

    result = await agent.consolidate(conv_id, fresh_user)
    assert result["user_state"] == "refreshed"
    assert state_calls == [(fresh_user, conv_id)]
