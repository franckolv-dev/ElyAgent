"""Unit tests for arena_service -- ELO update logic and match flow.

The ELO math is pure and can be tested without any LLM call.  We patch
the candidate pool for the end-to-end match flow so no real provider is
contacted.

The arena_service uses ``from app.database import async_session`` *inline*
inside each function, so the patch target is ``app.database.async_session``.
We build a fresh in-memory engine + sessionmaker per test to get clean
tables (import ``app.models.arena`` first so ``Base.metadata`` knows about
them before ``create_all``).

Run with:  cd backend && uv run --with pytest pytest tests/test_arena_service.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
# Importing the models registers them on Base.metadata (required for create_all)
from app.models import arena as _arena  # noqa: F401
from app.services import arena_service
from app.services.arena_service import _ELO_K, _ELO_START, _expected


# ---------------------------------------------------------------------------
# Per-test fresh DB fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def temp_session():
    """Yield an ``async_sessionmaker`` bound to a throwaway in-memory SQLite.

    The fixture patches ``app.database.async_session`` for the test so that
    the arena_service's lazy ``from app.database import async_session`` picks
    up the temp session.  Also ensures user sees clean tables for ArenaMatch
    and ArenaElo each run.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        # StaticPool keeps a single shared connection — required so every
        # session sees the same in-memory database (each new conn would
        # otherwise get its own empty DB).
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("app.database.async_session", test_session):
        yield test_session

    await engine.dispose()


# ---------------------------------------------------------------------------
# ELO pure math
# ---------------------------------------------------------------------------

class TestExpected:
    def test_equal_ratings_yields_half(self):
        assert abs(_expected(1500, 1500) - 0.5) < 1e-9

    def test_higher_rating_favored(self):
        # 400-point gap => expected ~0.909
        assert _expected(1800, 1400) == pytest.approx(0.909, abs=0.01)

    def test_lower_rating_disfavored(self):
        assert _expected(1200, 1500) < 0.25

    def test_mirror_sum_is_one(self):
        """expected(a,b) + expected(b,a) must equal 1."""
        assert _expected(1234, 1567) + _expected(1567, 1234) == pytest.approx(1.0, abs=1e-9)


class TestEloMove:
    """Replicate the ELO update formula and check boundary behaviour."""

    def _compute(self, elo_a, elo_b, vote):
        if vote == "a":
            score_a, score_b = 1.0, 0.0
        elif vote == "b":
            score_a, score_b = 0.0, 1.0
        else:
            score_a, score_b = 0.5, 0.5
        new_a = elo_a + _ELO_K * (score_a - _expected(elo_a, elo_b))
        new_b = elo_b + _ELO_K * (score_b - _expected(elo_b, elo_a))
        return new_a, new_b

    def test_equal_rating_winner_gains_K_over_two(self):
        new_a, new_b = self._compute(1000, 1000, "a")
        # Equal starts => 50/50 expected => winner gains K/2
        assert new_a == pytest.approx(1000 + _ELO_K / 2, abs=0.01)
        assert new_b == pytest.approx(1000 - _ELO_K / 2, abs=0.01)

    def test_underdog_upset_gains_more_than_K_over_two(self):
        """Weaker model beating stronger one gains more than K/2."""
        new_underdog, new_favorite = self._compute(1200, 1600, "a")
        assert new_underdog - 1200 > _ELO_K / 2
        assert 1600 - new_favorite > _ELO_K / 2

    def test_favorite_win_gains_little(self):
        """Heavy favorite beating underdog gains almost nothing."""
        new_fav, new_underdog = self._compute(1800, 1200, "a")
        assert new_fav - 1800 < _ELO_K / 4  # < 8 points

    def test_tie_is_symmetric_penalty(self):
        """both_bad == tie in our code — penalty flows from higher to lower."""
        new_high, new_low = self._compute(1600, 1200, "tie")
        # Higher-rated loses points on a draw against weaker
        assert new_high < 1600
        assert new_low > 1200
        # Sum conserved
        assert (new_high - 1600) + (new_low - 1200) == pytest.approx(0, abs=0.01)

    def test_constants_match_declared_values(self):
        assert _ELO_K == 32
        assert _ELO_START == 1000.0


# ---------------------------------------------------------------------------
# Match execution (mocked candidates + in-memory DB)
# ---------------------------------------------------------------------------

class _DummyLLM:
    def __init__(self, text: str):
        self._text = text

    async def ainvoke(self, messages):
        class _M:
            content = self._text
        return _M()


@pytest.mark.asyncio
async def test_run_match_returns_both_responses_and_persists(temp_session):
    """The happy path: two candidates, two responses, a match row persisted."""
    candidates = [
        ("fake/alpha", _DummyLLM("Alpha says hi.")),
        ("fake/beta", _DummyLLM("Beta disagrees.")),
    ]

    with patch.object(arena_service, "_available_candidates", return_value=candidates):
        result = await arena_service.run_match(
            prompt="Explique-moi la photosynthese en une phrase.",
            user_id="user-xyz",
        )

    assert result["model_a"] in {"fake/alpha", "fake/beta"}
    assert result["model_b"] in {"fake/alpha", "fake/beta"}
    assert result["model_a"] != result["model_b"]
    assert result["response_a"]
    assert result["response_b"]
    assert "match_id" in result
    assert result["latency_a_ms"] >= 0
    assert result["latency_b_ms"] >= 0


@pytest.mark.asyncio
async def test_run_match_requires_two_candidates():
    with patch.object(arena_service, "_available_candidates", return_value=[]):
        with pytest.raises(RuntimeError, match="deux modèles"):
            await arena_service.run_match("prompt", "u-1")


@pytest.mark.asyncio
async def test_vote_updates_elo_and_is_idempotent(temp_session):
    """A full match → vote → leaderboard round-trip."""
    candidates = [
        ("fake/alpha", _DummyLLM("A")),
        ("fake/beta", _DummyLLM("B")),
    ]

    with patch.object(arena_service, "_available_candidates", return_value=candidates):
        match = await arena_service.run_match("q", "u-1")

    # Vote 'a' wins
    result = await arena_service.record_vote(match["match_id"], "u-1", "a")
    assert result["vote"] == "a"
    assert result["elo"][match["model_a"]] > _ELO_START
    assert result["elo"][match["model_b"]] < _ELO_START

    # Re-voting is rejected
    with pytest.raises(ValueError, match="deja"):
        await arena_service.record_vote(match["match_id"], "u-1", "a")

    # Other users cannot vote on someone else's match
    with pytest.raises(PermissionError):
        await arena_service.record_vote(match["match_id"], "other-user", "b")


@pytest.mark.asyncio
async def test_vote_rejects_unknown_value(temp_session):
    with pytest.raises(ValueError, match="invalide"):
        await arena_service.record_vote("does-not-matter", "u", "maybe")
