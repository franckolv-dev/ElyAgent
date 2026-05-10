# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/analytics_service.py
# @brief      Analytics service — query usage statistics from the DB.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Analytics service — query usage statistics from the DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from app.database import async_session
from app.models.usage_log import UsageLog


# Pricing table (USD per 1M tokens, approximate)
_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-haiku-4-5-20251001": (0.25, 1.25),
    "claude-haiku-3-5": (0.25, 1.25),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-3-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-opus-4-5-20251101": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    # Zhipu AI — GLM (prefix caching reduces effective input cost by ~80%)
    "glm-4.7":    (0.14, 0.14),   # ~€0.13/M input+output (fixed/month plan)
    "glm-4-plus": (0.07, 0.07),
    "glm-4-air":  (0.014, 0.014),
    "glm-4-flash":(0.0, 0.0),    # gratuit
    # Mistral (USD per 1M tokens, non-cached input). The `*-latest` aliases
    # track Mistral's newest tagged release; pricing here is the historical
    # tier price — Mistral keeps it stable across generations within a tier.
    "mistral-small-latest": (0.2, 0.6),
    "mistral-medium-latest": (2.7, 8.1),
    "mistral-large-latest": (8.0, 24.0),
    # Magistral reasoning family — slightly more expensive than the
    # standard medium tier because of the longer reasoning trace.
    "magistral-medium-2509": (3.0, 9.0),
    # Codestral — code-focused, similar tier to small.
    "codestral-latest": (0.3, 0.9),
    # DeepSeek (USD per 1M tokens, non-cached input)
    # v4 family — 1M context, tool calling supported, current generation.
    # Pricing as of mai 2026 — DeepSeek runs frequent promo discounts so
    # actual billed cost may be lower (cf. their dashboard).
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    # Legacy aliases (deprecation announced — kept until DeepSeek removes them)
    "deepseek-chat": (0.014, 0.028),
    "deepseek-reasoner": (0.55, 2.19),
    # Gemini (tarifs au million de tokens, tier payant)
    "gemini-3.1-pro-preview": (2.5, 15.0),
    "gemini-3-flash-preview": (0.075, 0.30),
    "gemini-3.1-flash-lite-preview": (0.0, 0.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.5-flash-lite": (0.0, 0.0),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
    # Generic fallback
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD based on token counts and model pricing."""
    prices = _PRICING.get(model, (1.0, 3.0))  # default: $1/$3 per 1M
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


async def get_summary(user_id: str, days: int = 30) -> dict[str, Any]:
    """Get aggregated stats for the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        result = await db.execute(
            select(
                func.count(UsageLog.id).label("total_requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0).label("total_cost"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            ).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
            )
        )
        row = result.first()

    return {
        "total_requests": row.total_requests or 0,
        "total_tokens": row.total_tokens or 0,
        "total_cost_usd": round(row.total_cost or 0.0, 4),
        "input_tokens": row.input_tokens or 0,
        "output_tokens": row.output_tokens or 0,
        "period_days": days,
    }


async def get_daily_usage(user_id: str, days: int = 30) -> list[dict]:
    """Get per-day token usage and cost for the last N days.

    Backfille les jours sans activité avec des zéros pour que le dashboard
    affiche une frise temporelle continue (sinon ``group_by(day)`` ne renvoyait
    que les jours avec des entrées et la barre 'aujourd'hui' disparaissait
    quand l'utilisateur n'avait encore rien fait).
    """
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=days - 1)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        result = await db.execute(
            select(
                func.date(UsageLog.timestamp).label("day"),
                func.count(UsageLog.id).label("requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0).label("cost"),
            ).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
            ).group_by("day").order_by("day")
        )
        rows = result.all()

    # Index par jour (str) — func.date() peut renvoyer date ou str selon le driver
    by_day: dict[str, dict] = {
        str(r.day): {
            "day": str(r.day),
            "requests": r.requests,
            "tokens": r.tokens,
            "cost": round(r.cost, 4),
        }
        for r in rows
    }

    # Backfill : un point par jour sur toute la fenêtre
    out: list[dict] = []
    for i in range(days):
        d = start_day + timedelta(days=i)
        key = d.isoformat()
        if key in by_day:
            out.append(by_day[key])
        else:
            out.append({"day": key, "requests": 0, "tokens": 0, "cost": 0.0})
    return out


async def get_skill_usage(user_id: str, days: int = 30) -> list[dict]:
    """Get top skills used in the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        result = await db.execute(
            select(
                UsageLog.skill_used,
                func.count(UsageLog.id).label("count"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            ).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
                UsageLog.skill_used.isnot(None),
            ).group_by(UsageLog.skill_used)
            .order_by(func.count(UsageLog.id).desc())
            .limit(10)
        )
        rows = result.all()

    return [
        {"skill": r.skill_used, "count": r.count, "tokens": r.tokens}
        for r in rows
    ]


async def get_hitl_stats(user_id: str, days: int = 30) -> dict:
    """Get HITL decision breakdown."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        result = await db.execute(
            select(
                UsageLog.hitl_decision,
                func.count(UsageLog.id).label("count"),
            ).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
                UsageLog.hitl_decision.isnot(None),
            ).group_by(UsageLog.hitl_decision)
        )
        rows = result.all()

    totals = {"allow": 0, "deny": 0, "ban": 0}
    for r in rows:
        if r.hitl_decision in totals:
            totals[r.hitl_decision] = r.count
    return totals


async def get_provider_breakdown(user_id: str, days: int = 30) -> list[dict]:
    """Get usage breakdown by LLM provider for the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        result = await db.execute(
            select(
                UsageLog.provider,
                UsageLog.model,
                func.count(UsageLog.id).label("requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0).label("cost"),
            ).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
                UsageLog.provider.isnot(None),
            ).group_by(UsageLog.provider, UsageLog.model)
            .order_by(func.count(UsageLog.id).desc())
        )
        rows = result.all()

    return [
        {
            "provider": r.provider or "unknown",
            "model": r.model or "unknown",
            "requests": r.requests,
            "tokens": r.tokens,
            "cost": round(r.cost, 4),
        }
        for r in rows
    ]


async def log_usage(
    user_id: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    conversation_id: str | None = None,
    skill_used: str | None = None,
    channel: str = "web",
    hitl_decision: str | None = None,
    hitl_action: str | None = None,
) -> None:
    """Record a usage log entry. Called after each agent invocation."""
    cost = estimate_cost(model, input_tokens, output_tokens)
    entry = UsageLog(
        user_id=user_id,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=cost,
        conversation_id=conversation_id,
        skill_used=skill_used,
        channel=channel,
        hitl_decision=hitl_decision,
        hitl_action=hitl_action,
    )
    try:
        async with async_session() as db:
            db.add(entry)
            await db.commit()
    except Exception:
        pass  # Analytics logging is non-critical
