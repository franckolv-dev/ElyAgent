# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_user_state_endpoint.py
# @brief      Sprint 3 Jalon 3 — pin the contract of /api/me/state and
#             /api/me/state/recompute. Tests hit the handler functions
#             directly (no TestClient, no auth round-trip) so they stay
#             fast and hermetic.
# @license    MIT
# =============================================================================
"""Tests for `app/routers/user_state.py` — Sprint 3 Jalon 3."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# Fixture : throw-away user + clean USER_STATE_DISABLED between tests
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("USER_STATE_DISABLED", raising=False)
    yield


@pytest_asyncio.fixture
async def fresh_user():
    """User row + cleanup after the test. The state row + conversations
    are dropped on teardown too."""
    from app.database import async_session, init_db
    from app.models.conversation import Conversation
    from app.models.user import User
    from app.models.user_state import UserState
    from sqlalchemy import select

    await init_db()
    uid = f"test_us_e_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"use_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    yield uid
    async with async_session() as db:
        for model in (UserState, Conversation):
            for r in (await db.execute(
                select(model).where(model.user_id == uid)
            )).scalars():
                await db.delete(r)
        u = (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one_or_none()
        if u is not None:
            await db.delete(u)
        await db.commit()


def _fake_user(uid: str):
    """Lightweight stand-in for `User` ORM rows when the handler only
    needs ``.id``. Avoids pulling the full SQLAlchemy session into the
    test path."""
    class _U:
        id = uid
    return _U()


# ─────────────────────────────────────────────────────────────────────────
# _wants_json — content negotiation
# ─────────────────────────────────────────────────────────────────────────


def test_wants_json_format_query_param_wins() -> None:
    from app.routers.user_state import _wants_json
    assert _wants_json("json", "text/markdown") is True
    assert _wants_json("markdown", "application/json") is False


def test_wants_json_accept_header_when_no_format() -> None:
    from app.routers.user_state import _wants_json
    assert _wants_json(None, "application/json") is True
    assert _wants_json(None, "text/markdown") is False


def test_wants_json_default_when_both_missing() -> None:
    """No format hint at all → JSON (state is structured by nature)."""
    from app.routers.user_state import _wants_json
    assert _wants_json(None, "") is True


# ─────────────────────────────────────────────────────────────────────────
# GET /api/me/state — read handler
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_user_state_returns_defaults_for_unseen_user(fresh_user: str) -> None:
    from app.routers.user_state import read_user_state
    resp = await read_user_state(
        format="json",
        accept="application/json",
        current_user=_fake_user(fresh_user),
    )
    # JSONResponse has .body bytes
    body = json.loads(resp.body)
    assert body["mood"] == "neutral"
    assert body["current_focus"] == ""
    assert body["recent_topics"] == []
    assert body["open_loops"] == []
    assert body["energy_budget"] == "normal"
    assert body["disabled"] is False
    assert body["updated_at"] is None  # no row yet
    assert body["prompt_version"] is None


@pytest.mark.asyncio
async def test_read_user_state_returns_persisted_state(fresh_user: str) -> None:
    from app.routers.user_state import read_user_state
    from app.services.learning.user_state import set_user_state

    await set_user_state(fresh_user, {
        "mood": "focused",
        "current_focus": "Sprint 3 Jalon 3",
        "recent_topics": ["endpoint", "ui"],
        "energy_budget": "high",
    })
    resp = await read_user_state(
        format="json",
        accept="application/json",
        current_user=_fake_user(fresh_user),
    )
    body = json.loads(resp.body)
    assert body["mood"] == "focused"
    assert body["current_focus"] == "Sprint 3 Jalon 3"
    assert "endpoint" in body["recent_topics"]
    assert body["updated_at"] is not None  # row exists now


@pytest.mark.asyncio
async def test_read_user_state_markdown_format(fresh_user: str) -> None:
    from app.routers.user_state import read_user_state
    from app.services.learning.user_state import set_user_state

    await set_user_state(fresh_user, {
        "mood": "playful",
        "current_focus": "endpoint test",
    })
    resp = await read_user_state(
        format="markdown",
        accept="text/markdown",
        current_user=_fake_user(fresh_user),
    )
    # PlainTextResponse keeps body as bytes
    text = resp.body.decode()
    assert "<user_state>" in text
    assert "mood: playful" in text


@pytest.mark.asyncio
async def test_read_user_state_markdown_empty_when_no_state(fresh_user: str) -> None:
    """Empty state should not crash the markdown path."""
    from app.routers.user_state import read_user_state
    resp = await read_user_state(
        format="markdown",
        accept="text/markdown",
        current_user=_fake_user(fresh_user),
    )
    text = resp.body.decode()
    # The formatter returns "" for an empty state — handler falls back
    # to a marker so the UI doesn't render a blank page.
    assert text.strip() == "(état vide)"


@pytest.mark.asyncio
async def test_read_user_state_surfaces_kill_switch(
    monkeypatch, fresh_user: str,
) -> None:
    monkeypatch.setenv("USER_STATE_DISABLED", "1")
    from app.routers.user_state import read_user_state
    resp = await read_user_state(
        format="json",
        accept="application/json",
        current_user=_fake_user(fresh_user),
    )
    body = json.loads(resp.body)
    assert body["disabled"] is True


# ─────────────────────────────────────────────────────────────────────────
# POST /api/me/state/recompute — refresh handler
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_short_circuits_when_disabled(
    monkeypatch, fresh_user: str,
) -> None:
    monkeypatch.setenv("USER_STATE_DISABLED", "1")
    from app.routers.user_state import recompute_user_state

    # Even if compute_user_state were called, we'd want to know — so
    # blow up to make any leak obvious.
    async def trip(*_a, **_kw):
        raise AssertionError("compute_user_state should NOT be called when disabled")
    monkeypatch.setattr(
        "app.routers.user_state.compute_user_state", trip
    )

    resp = await recompute_user_state(
        conversation_id=None,
        current_user=_fake_user(fresh_user),
    )
    body = json.loads(resp.body)
    assert body["refreshed"] is False
    assert body["reason"] == "disabled"
    assert body["disabled"] is True


@pytest.mark.asyncio
async def test_recompute_no_conversations_returns_no_change(fresh_user: str) -> None:
    """Without any conv history, the recompute must be a no-op rather
    than a 404 or a crash."""
    from app.routers.user_state import recompute_user_state
    resp = await recompute_user_state(
        conversation_id=None,
        current_user=_fake_user(fresh_user),
    )
    body = json.loads(resp.body)
    assert body["refreshed"] is False
    assert body["reason"] == "no_conversations"
    # Defaults are still returned
    assert body["mood"] == "neutral"


@pytest.mark.asyncio
async def test_recompute_uses_latest_conv_and_returns_new_state(
    monkeypatch, fresh_user: str,
) -> None:
    from app.database import async_session
    from app.models.conversation import Conversation
    from app.routers.user_state import recompute_user_state

    # Seed a conversation so _latest_conversation_id finds one
    async with async_session() as db:
        conv = Conversation(user_id=fresh_user, title="seed conv")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = str(conv.id)

    # Stub compute_user_state so we don't hit the LLM
    new_state = {
        "mood": "focused",
        "current_focus": "from recompute endpoint",
        "recent_topics": ["endpoint"],
        "open_loops": [],
        "energy_budget": "high",
    }

    async def fake_compute(user_id, conversation_id=None, **_kw):
        assert user_id == fresh_user
        assert conversation_id == conv_id
        # Persist so the handler's "did it change?" check reflects reality
        from app.services.learning.user_state import set_user_state
        return await set_user_state(user_id, new_state)

    monkeypatch.setattr(
        "app.routers.user_state.compute_user_state", fake_compute
    )

    resp = await recompute_user_state(
        conversation_id=None,
        current_user=_fake_user(fresh_user),
    )
    body = json.loads(resp.body)
    assert body["refreshed"] is True
    assert body["source_conversation_id"] == conv_id
    assert body["mood"] == "focused"
    assert "endpoint" in body["recent_topics"]


@pytest.mark.asyncio
async def test_recompute_explicit_conversation_id_overrides_latest(
    monkeypatch, fresh_user: str,
) -> None:
    """If the caller passes ``?conversation_id=X``, the handler must use
    X even when a more recent conversation exists. Since the IDOR fix
    A-2 (revue 2026-06-10) X must be a real conversation owned by the
    caller — an arbitrary id now 404s (see
    tests/test_idor_conversation_ownership.py)."""
    from app.database import async_session
    from app.models.conversation import Conversation
    from app.routers.user_state import recompute_user_state
    seen = []

    # Two conversations — the explicit (older) one must win over latest.
    async with async_session() as db:
        older = Conversation(user_id=fresh_user, title="older conv")
        newer = Conversation(user_id=fresh_user, title="newer conv")
        db.add_all([older, newer])
        await db.commit()
        await db.refresh(older)
        older_id = str(older.id)

    async def fake_compute(user_id, conversation_id=None, **_kw):
        seen.append(conversation_id)
        from app.services.learning.user_state import get_user_state
        return await get_user_state(user_id)

    monkeypatch.setattr(
        "app.routers.user_state.compute_user_state", fake_compute
    )

    resp = await recompute_user_state(
        conversation_id=older_id,
        current_user=_fake_user(fresh_user),
    )
    assert resp.status_code == 200
    assert seen == [older_id]


@pytest.mark.asyncio
async def test_recompute_swallows_compute_exceptions(
    monkeypatch, fresh_user: str,
) -> None:
    """compute_user_state is supposed to be best-effort and never raise,
    but if a bug slips through, the endpoint must still return 200 with
    refreshed=False."""
    from app.database import async_session
    from app.models.conversation import Conversation
    from app.routers.user_state import recompute_user_state

    async with async_session() as db:
        conv = Conversation(user_id=fresh_user, title="seed conv")
        db.add(conv)
        await db.commit()

    async def crashing(*_a, **_kw):
        raise RuntimeError("forced")
    monkeypatch.setattr(
        "app.routers.user_state.compute_user_state", crashing
    )

    resp = await recompute_user_state(
        conversation_id=None,
        current_user=_fake_user(fresh_user),
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["refreshed"] is False


# ─────────────────────────────────────────────────────────────────────────
# Router registration — pin the path
# ─────────────────────────────────────────────────────────────────────────


def test_router_paths_are_registered() -> None:
    from app.routers.user_state import router
    paths = {r.path for r in router.routes}
    assert "/api/me/state" in paths
    assert "/api/me/state/recompute" in paths
    assert "/api/me/state/_health" in paths


def test_router_registered_in_main_app() -> None:
    """Make sure main.py actually mounts the router so the endpoint is
    reachable in prod, not just locally."""
    import inspect

    import app.main as main_module
    src = inspect.getsource(main_module)
    assert "user_state_router" in src
    assert "user_state_router.router" in src
