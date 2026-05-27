# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tier_s.py
# @brief      Sprint 4b Phase 2 — Tier S (Skill creation) provider + budget
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# =============================================================================
"""Tier S — dedicated LLM lane for skill creation + iteration.

Distinct from the user-facing tiers A/B/C/IMG/MAINTENANCE. Used by the
nightly skill_creator (Phase 3) and the eval iteration loop. Carries
its own monthly budget cap because Opus is expensive: 5 iterations on a
skill at ~10k tokens each = ~0.50-1€ per skill candidate.

Primary  : Claude Opus 4.5 (best at iterative code/playbook generation,
           via langchain-anthropic with prompt-caching beta)
Fallback : DeepSeek v4-pro (already used by tier C, no extra setup)

Spending is recorded in the existing ``usage_logs`` table with
``skill_used = "tier_s.<purpose>"`` so the budget query reuses the same
audit surface as user-facing LLM calls. Reset of the monthly budget is
implicit (we sum over the current calendar month).

Pattern d'inspiration : design note hermes-skills-self-improvement.md §3 Q1.
Implémentation : code maison.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import func, select

from app.database import async_session

logger = logging.getLogger(__name__)


# ── Defaults (overridable by env) ───────────────────────────────────────────

_DEFAULT_PRIMARY_MODEL = "claude-opus-4-5"
_DEFAULT_FALLBACK_MODEL = "deepseek-reasoner"
DEFAULT_MONTHLY_BUDGET_USD = 50.0


# ── Rough cost table (USD per million tokens, input / output) ──────────────
# Numbers from official pricing pages at end-2025; admin can override the
# whole dict via the future settings UI if pricing shifts. Keys are
# prefixes so any "claude-opus-*" variant maps to the same rate.
_COST_PER_MTOKEN_USD: dict[str, tuple[float, float]] = {
    "claude-opus":       (15.00, 75.00),
    "claude-sonnet":     ( 3.00, 15.00),  # sonnet (not used by tier S, kept for completeness)
    "deepseek-reasoner": ( 0.55,  2.19),
    "deepseek-chat":     ( 0.27,  1.10),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of a tier-S call from token counts.

    Linear lookup against ``_COST_PER_MTOKEN_USD`` by model-name prefix.
    Returns 0.0 for unknown models — better to under-report than crash
    the budget guard.
    """
    model_lc = (model or "").lower()
    for prefix, (in_rate, out_rate) in _COST_PER_MTOKEN_USD.items():
        if prefix in model_lc:
            return round(
                (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0,
                6,
            )
    return 0.0


# ── Spending query ──────────────────────────────────────────────────────────


def _month_start(now: datetime | None = None) -> datetime:
    """First instant of the current calendar month, UTC. Pure helper for tests."""
    n = now or datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_monthly_spend_usd(now: datetime | None = None) -> float:
    """Sum cost_usd over the current month for tier_s.* skill_used rows."""
    from app.models.usage_log import UsageLog

    start = _month_start(now)
    try:
        async with async_session() as db:
            result = await db.execute(
                select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0)).where(
                    UsageLog.timestamp >= start,
                    UsageLog.skill_used.like("tier_s.%"),
                )
            )
            value = result.scalar_one()
            return float(value or 0.0)
    except Exception as exc:
        logger.debug("get_monthly_spend_usd failed (swallowed): %s", exc)
        return 0.0


def _budget_cap_usd() -> float:
    """Monthly cap from env. ``<= 0`` means no cap (allow forever)."""
    raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_USD")
    if raw is None:
        raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_EUR")  # accept either, parity ≈ 1:1
    try:
        return float(raw) if raw is not None else DEFAULT_MONTHLY_BUDGET_USD
    except ValueError:
        logger.warning(
            "tier_s: invalid LLM_TIER_S_MONTHLY_BUDGET_USD=%r — using default %s",
            raw, DEFAULT_MONTHLY_BUDGET_USD,
        )
        return DEFAULT_MONTHLY_BUDGET_USD


async def is_primary_within_budget() -> bool:
    """True if monthly tier-S spend is still below the cap.

    Treats cap ``<= 0`` as "disabled" (always allow primary).
    """
    cap = _budget_cap_usd()
    if cap <= 0:
        return True
    return (await get_monthly_spend_usd()) < cap


# ── Usage recording ─────────────────────────────────────────────────────────


async def record_tier_s_usage(
    *,
    user_id: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    purpose: str,
    conversation_id: str | None = None,
) -> str | None:
    """Persist one tier-S call in ``usage_logs``.

    ``purpose`` is appended to ``"tier_s."`` to form the ``skill_used``
    discriminator (e.g. ``"tier_s.skill_creator"`` /
    ``"tier_s.skill_eval"``). The budget query filters on this prefix.

    Never raises — best-effort accounting. Returns the new row id or None.
    """
    if not user_id:
        return None
    try:
        from app.models.usage_log import UsageLog

        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        row = UsageLog(
            user_id=user_id,
            model=model,
            provider=provider,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(input_tokens + output_tokens),
            cost_usd=cost,
            skill_used=f"tier_s.{purpose}",
            conversation_id=conversation_id,
            channel="tier_s",
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("record_tier_s_usage failed (swallowed): %s", exc)
        return None


# ── LLM factory ─────────────────────────────────────────────────────────────


TierSPick = Literal["primary", "fallback", "none"]


def _build_primary() -> Any | None:
    """Build the Opus-4.5 (or env-overridden) ChatAnthropic. Returns None if
    no API key is configured — graceful degradation, the caller falls
    back to DeepSeek."""
    try:
        from langchain_anthropic import ChatAnthropic
        from app.config import get_settings
        from app.services.llm_provider import get_runtime_key

        api_key = get_runtime_key("anthropic") or get_settings().anthropic_api_key
        if not api_key:
            logger.info("tier_s: no Anthropic API key — primary unavailable")
            return None

        model = os.getenv("LLM_TIER_S_PRIMARY_MODEL", _DEFAULT_PRIMARY_MODEL)
        max_tokens = int(os.getenv("LLM_TIER_S_MAX_TOKENS", "8192"))

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=0.2,  # low — we want consistent skill output, not creative riffs
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
            },
        )
    except Exception as exc:
        logger.warning("tier_s: failed to build primary (%s)", exc)
        return None


def _build_fallback() -> Any | None:
    """Build DeepSeek v4-pro reasoner via the existing _make_qwen_api path
    (DeepSeek uses an OpenAI-compatible endpoint)."""
    try:
        from langchain_openai import ChatOpenAI
        from app.config import get_settings
        from app.services.llm_provider import (
            _deepseek_extra_body,
            get_runtime_key,
        )

        settings = get_settings()
        api_key = get_runtime_key("deepseek") or settings.deepseek_api_key
        if not api_key:
            logger.info("tier_s: no DeepSeek API key — fallback unavailable")
            return None

        model = os.getenv("LLM_TIER_S_FALLBACK_MODEL", _DEFAULT_FALLBACK_MODEL)
        max_tokens = int(os.getenv("LLM_TIER_S_MAX_TOKENS", "8192"))
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=0.2,
            **_deepseek_extra_body(model),
        )
    except Exception as exc:
        logger.warning("tier_s: failed to build fallback (%s)", exc)
        return None


async def get_tier_s_llm(*, force_fallback: bool = False) -> tuple[Any | None, TierSPick]:
    """Return ``(llm, pick)`` for one tier-S call.

    ``pick`` is ``"primary"`` (Opus, within budget), ``"fallback"``
    (DeepSeek), or ``"none"`` (neither provider configured). Callers
    check ``pick == "none"`` to abort gracefully.

    ``force_fallback=True`` skips the budget check + Opus build, useful
    for the eval loop's deterministic re-runs where we don't want to
    burn Opus tokens.
    """
    if not force_fallback and await is_primary_within_budget():
        primary = _build_primary()
        if primary is not None:
            return primary, "primary"
        logger.info("tier_s: primary unavailable, falling back to DeepSeek")
    fallback = _build_fallback()
    if fallback is not None:
        return fallback, "fallback"
    return None, "none"
