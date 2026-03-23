"""Analytics service — query usage statistics from the DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from app.database import async_session
from app.models.usage_log import UsageLog


# Pricing table (USD per 1M tokens, approximate)
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.25, 1.25),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "mistral-small-latest": (0.2, 0.6),
    "mistral-medium-latest": (2.7, 8.1),
    "gpt-4o-mini": (0.15, 0.60),
    "deepseek-chat": (0.014, 0.028),
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
    """Get per-day token usage and cost for the last N days."""
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

    return [
        {
            "day": str(r.day),
            "requests": r.requests,
            "tokens": r.tokens,
            "cost": round(r.cost, 4),
        }
        for r in rows
    ]


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
