# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_user_state.py
# @brief      Sprint 3 Jalon 1 — pin the user_state service contract :
#             defaults always present, upsert idempotency, LLM-failure
#             tolerance, sanitisation bounds, formatter block output.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `app/services/learning/user_state.py` — Sprint 3 Jalon 1."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.learning.user_state import (
    ALLOWED_ENERGY,
    DEFAULT_STATE,
    MAX_FOCUS_CHARS,
    MAX_LIST_LEN,
    MAX_LOOP_CHARS,
    MAX_TOPIC_CHARS,
    _merge_with_defaults,
    compute_user_state,
    format_user_state_block,
    get_user_state,
    set_user_state,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixture: fresh schema + a throw-away user per test
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def user_id() -> str:
    """Ensure the schema exists (no-op locally, mandatory on CI's
    in-memory sqlite) and insert a throw-away User row so the
    foreign-key constraint on `user_states.user_id` is satisfied."""
    from app.database import async_session, init_db
    from app.models.user import User
    from app.models.user_state import UserState

    await init_db()
    uid = f"test_us_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"us_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    yield uid
    # Cleanup : drop the row + state so re-runs against a persistent DB
    # don't pile up clutter.
    async with async_session() as db:
        row = (await db.execute(
            select(UserState).where(UserState.user_id == uid)
        )).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
        u = (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one_or_none()
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# DEFAULT_STATE + _merge_with_defaults
# ─────────────────────────────────────────────────────────────────────────


def test_default_state_has_all_five_keys() -> None:
    assert set(DEFAULT_STATE.keys()) == {
        "mood", "current_focus", "recent_topics", "open_loops", "energy_budget",
    }
    assert DEFAULT_STATE["mood"] == "neutral"
    assert DEFAULT_STATE["energy_budget"] == "normal"
    assert DEFAULT_STATE["recent_topics"] == []
    assert DEFAULT_STATE["open_loops"] == []


def test_merge_with_defaults_fills_missing_keys() -> None:
    out = _merge_with_defaults({"mood": "focused"})
    assert out["mood"] == "focused"
    assert out["current_focus"] == ""
    assert out["energy_budget"] == "normal"
    assert out["recent_topics"] == []


def test_merge_with_defaults_clips_overlong_values() -> None:
    huge_focus = "x" * (MAX_FOCUS_CHARS + 50)
    huge_topic = "y" * (MAX_TOPIC_CHARS + 50)
    huge_loop = "z" * (MAX_LOOP_CHARS + 50)
    out = _merge_with_defaults({
        "current_focus": huge_focus,
        "recent_topics": [huge_topic] * (MAX_LIST_LEN + 3),
        "open_loops": [huge_loop] * (MAX_LIST_LEN + 3),
    })
    assert len(out["current_focus"]) == MAX_FOCUS_CHARS
    assert len(out["recent_topics"]) == MAX_LIST_LEN
    assert all(len(t) == MAX_TOPIC_CHARS for t in out["recent_topics"])
    assert len(out["open_loops"]) == MAX_LIST_LEN
    assert all(len(t) == MAX_LOOP_CHARS for t in out["open_loops"])


def test_merge_with_defaults_validates_energy_budget() -> None:
    assert _merge_with_defaults({"energy_budget": "high"})["energy_budget"] == "high"
    assert _merge_with_defaults({"energy_budget": "  LOW "})["energy_budget"] == "low"
    # Unknown value silently falls back to default
    assert _merge_with_defaults({"energy_budget": "turbo"})["energy_budget"] == "normal"
    # Make sure the allowlist is stable
    assert ALLOWED_ENERGY == frozenset({"high", "normal", "low"})


def test_merge_with_defaults_handles_garbage_input() -> None:
    """Non-dict input must not crash."""
    out = _merge_with_defaults("not a dict")  # type: ignore[arg-type]
    assert out == DEFAULT_STATE


def test_merge_with_defaults_drops_empty_list_entries() -> None:
    out = _merge_with_defaults({
        "recent_topics": ["a", "   ", "", "b", None],  # type: ignore[list-item]
    })
    assert out["recent_topics"] == ["a", "b"]


# ─────────────────────────────────────────────────────────────────────────
# get_user_state / set_user_state — async round-trip
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_state_returns_defaults_for_missing_user() -> None:
    out = await get_user_state(f"nope_{uuid.uuid4().hex[:6]}")
    assert out == DEFAULT_STATE
    # And empty user_id must not crash either
    assert await get_user_state("") == DEFAULT_STATE


@pytest.mark.asyncio
async def test_set_then_get_round_trip(user_id: str) -> None:
    written = await set_user_state(user_id, {
        "mood": "focused",
        "current_focus": "Sprint 3",
        "recent_topics": ["sprint", "roadmap"],
        "open_loops": ["clarifier le scope V2"],
        "energy_budget": "high",
    })
    assert written["mood"] == "focused"
    assert written["current_focus"] == "Sprint 3"
    assert written["recent_topics"] == ["sprint", "roadmap"]
    assert written["energy_budget"] == "high"

    reread = await get_user_state(user_id)
    assert reread == written


@pytest.mark.asyncio
async def test_set_user_state_partial_keeps_previous_values(user_id: str) -> None:
    """Partial update must NOT wipe fields the caller didn't send."""
    await set_user_state(user_id, {
        "mood": "focused",
        "current_focus": "Sprint 3",
        "energy_budget": "high",
    })
    # Now only update mood
    await set_user_state(user_id, {"mood": "fatigué"})
    final = await get_user_state(user_id)
    assert final["mood"] == "fatigué"
    assert final["current_focus"] == "Sprint 3"  # preserved
    assert final["energy_budget"] == "high"  # preserved


@pytest.mark.asyncio
async def test_set_user_state_idempotent(user_id: str) -> None:
    payload = {
        "mood": "focused",
        "current_focus": "Sprint 3",
        "recent_topics": ["a", "b"],
    }
    a = await set_user_state(user_id, payload)
    b = await set_user_state(user_id, payload)
    assert a == b


@pytest.mark.asyncio
async def test_get_user_state_resilient_to_corrupt_json(user_id: str) -> None:
    """Corrupt JSON in the row must not crash — defaults returned."""
    from app.database import async_session
    from app.models.user_state import UserState

    async with async_session() as db:
        db.add(UserState(user_id=user_id, state_json="{not json at all"))
        await db.commit()

    out = await get_user_state(user_id)
    assert out == DEFAULT_STATE


# ─────────────────────────────────────────────────────────────────────────
# compute_user_state — LLM injection + failure tolerance
# ─────────────────────────────────────────────────────────────────────────


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        return _FakeLLMResponse(self.payload)


class _CrashingLLM:
    async def ainvoke(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated LLM outage")


@pytest.mark.asyncio
async def test_compute_user_state_persists_llm_output(user_id: str) -> None:
    fake = _FakeLLM(json.dumps({
        "mood": "focused",
        "current_focus": "Sprint 3 UserState",
        "recent_topics": ["sprint", "vector"],
        "open_loops": ["valider la table"],
        "energy_budget": "high",
    }))
    out = await compute_user_state(
        user_id,
        messages=[type("M", (), {"role": "user", "content": "Tu progresses bien ?"})()],
        llm=fake,
    )
    assert fake.calls == 1
    assert out["mood"] == "focused"
    assert out["current_focus"] == "Sprint 3 UserState"

    persisted = await get_user_state(user_id)
    assert persisted == out


@pytest.mark.asyncio
async def test_compute_user_state_returns_current_on_llm_crash(user_id: str) -> None:
    """If the LLM throws, the current state must be returned untouched."""
    await set_user_state(user_id, {"current_focus": "préexistant"})
    out = await compute_user_state(
        user_id,
        messages=[type("M", (), {"role": "user", "content": "hello"})()],
        llm=_CrashingLLM(),
    )
    assert out["current_focus"] == "préexistant"


@pytest.mark.asyncio
async def test_compute_user_state_returns_current_on_garbage_json(user_id: str) -> None:
    await set_user_state(user_id, {"mood": "playful"})
    out = await compute_user_state(
        user_id,
        messages=[type("M", (), {"role": "user", "content": "hi"})()],
        llm=_FakeLLM("not even close to JSON"),
    )
    assert out["mood"] == "playful"  # unchanged


@pytest.mark.asyncio
async def test_compute_user_state_skips_when_no_messages(user_id: str) -> None:
    """Empty message slice → no LLM call, current state returned as-is."""
    fake = _FakeLLM('{"mood": "should_not_appear"}')
    await set_user_state(user_id, {"mood": "playful"})
    out = await compute_user_state(user_id, messages=[], llm=fake)
    assert fake.calls == 0
    assert out["mood"] == "playful"


@pytest.mark.asyncio
async def test_compute_user_state_strips_markdown_fences(user_id: str) -> None:
    """Tier MAINTENANCE small models sometimes wrap their JSON in
    ```json fences despite the instruction. The service must cope."""
    fenced = "```json\n" + json.dumps({"mood": "joueur"}) + "\n```"
    out = await compute_user_state(
        user_id,
        messages=[type("M", (), {"role": "user", "content": "hello"})()],
        llm=_FakeLLM(fenced),
    )
    assert out["mood"] == "joueur"


# ─────────────────────────────────────────────────────────────────────────
# format_user_state_block — prompt injection rendering
# ─────────────────────────────────────────────────────────────────────────


def test_format_user_state_block_empty_state_returns_empty_string() -> None:
    """Default state has no signal → we don't want to bloat the prompt
    with a useless XML block."""
    assert format_user_state_block(DEFAULT_STATE) == ""
    assert format_user_state_block({}) == ""


def test_format_user_state_block_with_signal_returns_xml() -> None:
    block = format_user_state_block({
        **DEFAULT_STATE,
        "mood": "focused",
        "current_focus": "Sprint 3",
        "recent_topics": ["sprint", "roadmap"],
        "open_loops": ["décider du tag v1.7"],
        "energy_budget": "high",
    })
    assert "<user_state>" in block
    assert "</user_state>" in block
    assert "mood: focused" in block
    assert "current_focus: Sprint 3" in block
    assert "sprint, roadmap" in block
    assert "décider du tag v1.7" in block
    assert "energy_budget: high" in block


def test_format_user_state_block_only_topics_no_loops() -> None:
    """An ``open_loops`` empty list must not produce a stray bullet."""
    block = format_user_state_block({
        **DEFAULT_STATE,
        "mood": "focused",
        "recent_topics": ["x"],
    })
    assert "<user_state>" in block
    assert "open_loops" not in block
