# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tier_s.py
# @brief      Sprint 4b Phase 2 — tests for the tier S LLM provider + budget
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `app/services/learning/tier_s.py` — Sprint 4b Phase 2.

Covers four layers :
  1. Cost estimation table (model prefix lookup, unknown defaults)
  2. Monthly spend query against ``usage_logs`` (sum, month boundary)
  3. Budget cap predicate (env override, disabled, default)
  4. Provider factory + ``get_tier_s_llm`` budget-aware switch
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database import async_session, init_db
from app.models.usage_log import UsageLog
from app.services.learning.tier_s import (
    DEFAULT_MONTHLY_BUDGET_USD,
    _budget_cap_usd,
    _month_start,
    estimate_cost_usd,
    get_monthly_spend_usd,
    get_tier_s_llm,
    is_primary_within_budget,
    record_tier_s_usage,
)


@pytest_asyncio.fixture
async def _seeded_user():
    """Seed a user so usage_log rows can carry user_id. Also clean any
    tier_s.* rows for that user before yielding so each test starts
    with $0 spent."""
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(
            UsageLog.__table__.select().where(UsageLog.user_id == "ts1")
        )).first()
        if (await db.execute(
            User.__table__.select().where(User.id == "ts1")
        )).first() is None:
            db.add(User(
                id="ts1",
                username="tier_s_test_user",
                email="ts1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        # Wipe pre-existing tier_s rows from earlier runs of this fixture
        await db.execute(
            delete(UsageLog).where(
                UsageLog.user_id == "ts1",
                UsageLog.skill_used.like("tier_s.%"),
            )
        )
        await db.commit()
    yield "ts1"


# ─────────────────────────────────────────────────────────────────────────
# estimate_cost_usd
# ─────────────────────────────────────────────────────────────────────────


def test_cost_opus_known_rate():
    """Opus is $15/1M input, $75/1M output (per docs end-2025)."""
    cost = estimate_cost_usd("claude-opus-4-5", 100_000, 50_000)
    expected = (100_000 * 15.00 + 50_000 * 75.00) / 1_000_000
    assert abs(cost - expected) < 1e-4


def test_cost_deepseek_reasoner():
    cost = estimate_cost_usd("deepseek-reasoner", 100_000, 50_000)
    expected = (100_000 * 0.55 + 50_000 * 2.19) / 1_000_000
    assert abs(cost - expected) < 1e-4


def test_cost_unknown_model_returns_zero():
    """An unknown model must return 0.0 — the budget guard prefers
    under-reporting to crashing on a model name it doesn't recognise."""
    assert estimate_cost_usd("nonexistent-model-9000", 1000, 1000) == 0.0


def test_cost_empty_model_returns_zero():
    assert estimate_cost_usd("", 1000, 1000) == 0.0


def test_cost_case_insensitive_match():
    """Prefix lookup is case-insensitive."""
    a = estimate_cost_usd("Claude-Opus-4-5", 1000, 1000)
    b = estimate_cost_usd("claude-opus-4-5", 1000, 1000)
    assert a == b
    assert a > 0


# ─────────────────────────────────────────────────────────────────────────
# _month_start helper
# ─────────────────────────────────────────────────────────────────────────


def test_month_start_returns_first_of_month_at_midnight():
    n = datetime(2026, 5, 27, 21, 47, 9, tzinfo=timezone.utc)
    out = _month_start(n)
    assert out == datetime(2026, 5, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# get_monthly_spend_usd
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_spend_empty_returns_zero(_seeded_user):
    assert (await get_monthly_spend_usd()) == 0.0


@pytest.mark.asyncio
async def test_monthly_spend_sums_tier_s_rows_only(_seeded_user):
    """Only ``skill_used LIKE 'tier_s.%'`` rows count toward the budget."""
    async with async_session() as db:
        # 3 rows: 2 tier_s, 1 not-tier_s
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=1.50, skill_used="tier_s.skill_creator",
        ))
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=2.25, skill_used="tier_s.skill_eval",
        ))
        db.add(UsageLog(
            user_id=_seeded_user, model="deepseek-chat", provider="deepseek",
            cost_usd=10.00, skill_used="agent.tool_call",  # NOT tier_s
        ))
        await db.commit()
    spend = await get_monthly_spend_usd()
    assert abs(spend - 3.75) < 1e-4


@pytest.mark.asyncio
async def test_monthly_spend_ignores_last_month(_seeded_user):
    """Rows from the previous month must NOT be counted."""
    now = datetime.now(timezone.utc)
    last_month = (now.replace(day=1) - timedelta(days=1))
    async with async_session() as db:
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=99.99, skill_used="tier_s.skill_creator",
            timestamp=last_month,
        ))
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=1.00, skill_used="tier_s.skill_creator",
            timestamp=now,
        ))
        await db.commit()
    spend = await get_monthly_spend_usd(now=now)
    assert abs(spend - 1.00) < 1e-4


# ─────────────────────────────────────────────────────────────────────────
# Budget cap predicate
# ─────────────────────────────────────────────────────────────────────────


def test_budget_cap_default(monkeypatch):
    monkeypatch.delenv("LLM_TIER_S_MONTHLY_BUDGET_USD", raising=False)
    monkeypatch.delenv("LLM_TIER_S_MONTHLY_BUDGET_EUR", raising=False)
    assert _budget_cap_usd() == DEFAULT_MONTHLY_BUDGET_USD


def test_budget_cap_env_usd_overrides(monkeypatch):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "12.50")
    assert _budget_cap_usd() == 12.5


def test_budget_cap_eur_alias_accepted(monkeypatch):
    """Accept LLM_TIER_S_MONTHLY_BUDGET_EUR too (parity ≈ 1:1)."""
    monkeypatch.delenv("LLM_TIER_S_MONTHLY_BUDGET_USD", raising=False)
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_EUR", "30")
    assert _budget_cap_usd() == 30.0


def test_budget_cap_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "not-a-number")
    assert _budget_cap_usd() == DEFAULT_MONTHLY_BUDGET_USD


@pytest.mark.asyncio
async def test_is_primary_within_budget_disabled_returns_true(monkeypatch, _seeded_user):
    """Cap ``<= 0`` disables the guard (always allow primary)."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "0")
    assert await is_primary_within_budget() is True


@pytest.mark.asyncio
async def test_is_primary_within_budget_blocks_when_over(monkeypatch, _seeded_user):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "5.00")
    async with async_session() as db:
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=10.00, skill_used="tier_s.skill_creator",
        ))
        await db.commit()
    assert await is_primary_within_budget() is False


@pytest.mark.asyncio
async def test_is_primary_within_budget_allows_when_under(monkeypatch, _seeded_user):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "50.00")
    async with async_session() as db:
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=10.00, skill_used="tier_s.skill_creator",
        ))
        await db.commit()
    assert await is_primary_within_budget() is True


# ─────────────────────────────────────────────────────────────────────────
# record_tier_s_usage
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_persists_row_with_tier_s_prefix(_seeded_user):
    rid = await record_tier_s_usage(
        user_id=_seeded_user,
        model="claude-opus-4-5",
        provider="anthropic",
        input_tokens=1000,
        output_tokens=500,
        purpose="skill_creator",
    )
    assert rid is not None
    async with async_session() as db:
        row = (await db.execute(
            UsageLog.__table__.select().where(UsageLog.id == rid)
        )).first()
    assert row is not None
    # row is a Row object — _mapping gives column access
    r = row._mapping
    assert r["skill_used"] == "tier_s.skill_creator"
    assert r["input_tokens"] == 1000
    assert r["output_tokens"] == 500
    assert r["total_tokens"] == 1500
    assert r["channel"] == "tier_s"
    # Cost is computed from the rate table
    expected = (1000 * 15.00 + 500 * 75.00) / 1_000_000
    assert abs(r["cost_usd"] - expected) < 1e-4


@pytest.mark.asyncio
async def test_record_usage_with_no_user_returns_none(_seeded_user):
    """Defensive: an empty user_id must not crash, just no-op."""
    out = await record_tier_s_usage(
        user_id="",
        model="claude-opus-4-5",
        provider="anthropic",
        input_tokens=1, output_tokens=1,
        purpose="skill_creator",
    )
    assert out is None


# ─────────────────────────────────────────────────────────────────────────
# get_tier_s_llm — provider switching
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tier_s_llm_force_fallback_skips_first(monkeypatch):
    """`force_fallback=True` must skip the FIRST item in the chain,
    even when budget allows it. Default chain is "anthropic,deepseek"
    so force_fallback picks deepseek."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus",
        lambda: object(),  # would be selected if not for force_fallback
    )
    fb_marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek",
        lambda: fb_marker,
    )
    llm, pick = await get_tier_s_llm(force_fallback=True)
    assert pick == "deepseek"
    assert llm is fb_marker


@pytest.mark.asyncio
async def test_get_tier_s_llm_picks_first_chain_item_under_budget(monkeypatch, _seeded_user):
    """Default chain → first item (anthropic) gets picked when budget allows."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)
    pr_marker = object()
    fb_marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", lambda: pr_marker,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: fb_marker,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "anthropic"
    assert llm is pr_marker


@pytest.mark.asyncio
async def test_get_tier_s_llm_skips_first_when_over_budget(monkeypatch, _seeded_user):
    """Over-budget skips item 0, picks item 1 (the next-in-chain)."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "1.00")
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)
    async with async_session() as db:
        db.add(UsageLog(
            user_id=_seeded_user, model="claude-opus-4-5", provider="anthropic",
            cost_usd=5.00, skill_used="tier_s.skill_creator",
        ))
        await db.commit()
    pr_marker = object()
    fb_marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", lambda: pr_marker,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: fb_marker,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "deepseek"
    assert llm is fb_marker


@pytest.mark.asyncio
async def test_get_tier_s_llm_returns_none_when_no_providers(monkeypatch):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", lambda: None,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: None,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_mistral_large", lambda: None,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "none"
    assert llm is None


@pytest.mark.asyncio
async def test_get_tier_s_llm_falls_through_chain_when_first_builds_none(
    monkeypatch, _seeded_user,
):
    """When budget allows but the first provider's build returns None
    (e.g. no API key), we should silently fall through to the next
    item in the chain."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)
    fb_marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", lambda: None,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: fb_marker,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "deepseek"
    assert llm is fb_marker


# ── Backlog #19 — LLM_TIER_S_CHAIN configurable ────────────────────────


@pytest.mark.asyncio
async def test_chain_env_picks_mistral_first_for_sovereignty(monkeypatch):
    """LLM_TIER_S_CHAIN=mistral,deepseek → Mistral picked first."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", "mistral,deepseek")
    mistral_marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_mistral_large",
        lambda: mistral_marker,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek",
        lambda: object(),
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "mistral"
    assert llm is mistral_marker


@pytest.mark.asyncio
async def test_chain_aliases_collapsed_to_canonical(monkeypatch):
    """`opus` / `claude` are aliases of `anthropic` — same builder,
    canonical name returned."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", "opus")  # alias of anthropic
    marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", lambda: marker,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "anthropic"  # canonical, not the alias
    assert llm is marker


@pytest.mark.asyncio
async def test_chain_unknown_provider_warns_and_skips(monkeypatch):
    """Unknown provider name in LLM_TIER_S_CHAIN is dropped + logged,
    not raised."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", "nonexistent,deepseek")
    marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: marker,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "deepseek"


@pytest.mark.asyncio
async def test_chain_empty_returns_none(monkeypatch):
    """LLM_TIER_S_CHAIN= (empty) or all-unknown → no provider attempted."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", " ,,")
    llm, pick = await get_tier_s_llm()
    assert pick == "none"
    assert llm is None


@pytest.mark.asyncio
async def test_chain_single_item_does_not_skip_on_force_fallback(monkeypatch):
    """If the chain has ONE provider, `force_fallback=True` doesn't
    yield 'none' — single-item chain has no alternative so we still
    try that single provider (otherwise deepseek-only setups would
    always fail under force_fallback)."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", "deepseek")
    marker = object()
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", lambda: marker,
    )
    llm, pick = await get_tier_s_llm(force_fallback=True)
    assert pick == "deepseek"
    assert llm is marker


@pytest.mark.asyncio
async def test_chain_dedups_repeated_aliases(monkeypatch):
    """LLM_TIER_S_CHAIN=opus,claude,anthropic must collapse to a single
    'anthropic' entry — no triple-attempt of the same provider."""
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("LLM_TIER_S_CHAIN", "opus,claude,anthropic,deepseek")
    call_count = {"opus": 0, "deepseek": 0}

    def _opus_build():
        call_count["opus"] += 1
        return None  # let it fall through

    def _ds_build():
        call_count["deepseek"] += 1
        return object()

    monkeypatch.setattr(
        "app.services.learning.tier_s._build_opus", _opus_build,
    )
    monkeypatch.setattr(
        "app.services.learning.tier_s._build_deepseek", _ds_build,
    )
    llm, pick = await get_tier_s_llm()
    assert pick == "deepseek"
    assert call_count["opus"] == 1  # NOT 3 — dedup'd
    assert call_count["deepseek"] == 1


def test_mistral_large_cost_in_rate_table():
    """Pin the Mistral Large rate so a future refactor doesn't drop it
    silently. Also documents the 7× savings vs Opus that motivates
    Backlog #19."""
    cost = estimate_cost_usd("mistral-large-latest", 1_000_000, 1_000_000)
    expected = (1_000_000 * 2.00 + 1_000_000 * 6.00) / 1_000_000
    assert abs(cost - expected) < 1e-4
    # Pin the 7-12× savings argument that motivates the sovereignty chain
    opus_cost = estimate_cost_usd("claude-opus-4-5", 1_000_000, 1_000_000)
    assert opus_cost / cost > 7.0
