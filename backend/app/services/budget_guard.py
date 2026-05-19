# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/budget_guard.py
# @brief      Budget guard — tracks LLM token usage per user (no hard cap yet)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Budget guard — observability layer for LLM cost (Phase 5A).

This module is intentionally tracking-ONLY for now. No hard cap, no
blocking. The user (Franck) wants to monitor Qwen API spend over the
first weeks before deciding on a per-user budget.

Persistence is handled via the existing UsageLog model — we don't add a
new table, just write rows from a single chokepoint (`record_llm_usage`)
called from `nodes.py` after each ainvoke.

Aggregation helpers (`get_summary`) power the /api/budget endpoint.

Coverage caveat
---------------
The current hook lives in the `general` agent node (backend/app/agent/nodes.py).
Sub-agent paths (workspace, infra, research…) run inside compiled subgraphs
that do their own LLM invocations and are NOT yet instrumented. For full
coverage in Phase 5B we'll move the hook into a LangChain callback handler
attached at LLM construction time. For now, observe Qwen / Gemini / Anthropic
cost via their respective dashboards as the source of truth, and use this
service for relative comparisons + per-conversation breakdowns.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select

from app.database import async_session
from app.models.usage_log import UsageLog

logger = logging.getLogger(__name__)

Period = Literal["day", "week", "month"]


# ──────────────────────────────────────────────────────────────────────────────
# Pricing table (USD per 1M tokens) — rough indicators, not authoritative.
# Used to compute an estimated cost in UsageLog. Update as providers shift.
# Local models (ollama, lm_studio) are billed at $0.
# ──────────────────────────────────────────────────────────────────────────────

_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    # provider → { model_substring: (input_per_1m, output_per_1m) }
    "anthropic": {
        "claude-opus-4":   (15.00, 75.00),
        "claude-sonnet-4": (3.00,  15.00),
        "claude-haiku-4":  (0.80,  4.00),
        "claude-opus":     (15.00, 75.00),
        "claude-sonnet":   (3.00,  15.00),
        "claude-haiku":    (0.25,  1.25),
    },
    "gemini": {
        "gemini-2.5-pro":   (1.25, 10.00),
        "gemini-2.5-flash": (0.075, 0.30),
        "gemini-1.5-pro":   (1.25, 5.00),
        "gemini-1.5-flash": (0.075, 0.30),
    },
    "qwen_api": {
        # Alibaba DashScope, EUR/CN region. Approximations.
        "qwen3.6-max":  (10.00, 30.00),
        "qwen3.6-plus": (1.00,  3.00),
        "qwen-max":     (10.00, 30.00),
        "qwen-plus":    (1.00,  3.00),
        "qwen-turbo":   (0.30,  0.60),
    },
    "deepseek": {
        "deepseek-chat":     (0.27, 1.10),
        "deepseek-reasoner": (0.55, 2.19),
    },
    "mistral": {
        "mistral-large":  (2.00, 6.00),
        "mistral-medium": (0.40, 2.00),
        "mistral-small":  (0.20, 0.60),
    },
    "zhipu": {
        "glm-4.7":   (0.50, 1.50),
        "glm-4-plus": (0.50, 1.50),
        "glm-4-flash": (0.05, 0.15),
    },
    "openrouter": {
        # Highly variable by underlying model — leave conservative default
        "default": (1.00, 3.00),
    },
    # Local: free
    "ollama":    {"default": (0.0, 0.0)},
    "lm_studio": {"default": (0.0, 0.0)},
}


def estimate_cost_usd(
    provider: str | None, model: str | None, input_tokens: int, output_tokens: int
) -> float:
    """Best-effort cost estimate in USD. Returns 0.0 when provider unknown."""
    if not provider:
        return 0.0
    table = _PRICING.get(provider, {})
    if not table:
        return 0.0
    pricing: tuple[float, float] | None = None
    if model:
        model_lower = model.lower()
        for key, prices in table.items():
            if key in model_lower:
                pricing = prices
                break
    if pricing is None:
        pricing = table.get("default")
    if pricing is None:
        return 0.0
    in_price, out_price = pricing
    return (input_tokens / 1_000_000.0) * in_price + (
        output_tokens / 1_000_000.0
    ) * out_price


# ──────────────────────────────────────────────────────────────────────────────
# Hot path — one fire-and-forget call per LLM ainvoke
# ──────────────────────────────────────────────────────────────────────────────

async def record_llm_usage(
    user_id: str,
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    skill_used: str | None = None,
    conversation_id: str | None = None,
    channel: str = "web",
    hitl_decision: str | None = None,
) -> None:
    """Persist a single LLM call into the usage_logs table."""
    if not user_id:
        return  # Anonymous calls (heartbeat with system uid) — skip
    try:
        cost = estimate_cost_usd(provider, model, input_tokens, output_tokens)
        async with async_session() as db:
            db.add(UsageLog(
                user_id=user_id,
                provider=provider,
                model=model,
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                total_tokens=int((input_tokens or 0) + (output_tokens or 0)),
                cost_usd=cost,
                skill_used=skill_used,
                conversation_id=conversation_id,
                channel=channel,
                hitl_decision=hitl_decision,
            ))
            await db.commit()
    except Exception as exc:
        # Telemetry must NEVER break the agent — log at WARN and move on.
        logger.warning("budget_guard.record_llm_usage failed: %s", exc)


def extract_usage_from_response(response) -> tuple[int, int]:
    """Best-effort extraction of (input_tokens, output_tokens) from a LangChain
    AIMessage. Different providers expose this differently.

    Supports:
    - LangChain standard: response.usage_metadata = {"input_tokens", "output_tokens", ...}
    - OpenAI-shaped:      response.response_metadata["token_usage"]
    - Anthropic-shaped:   response.response_metadata["usage"]
    """
    meta = getattr(response, "usage_metadata", None) or {}
    if isinstance(meta, dict) and ("input_tokens" in meta or "output_tokens" in meta):
        return int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0)

    rmeta = getattr(response, "response_metadata", None) or {}
    if isinstance(rmeta, dict):
        # OpenAI
        tu = rmeta.get("token_usage") or {}
        if tu:
            return int(tu.get("prompt_tokens", 0) or 0), int(tu.get("completion_tokens", 0) or 0)
        # Anthropic
        au = rmeta.get("usage") or {}
        if au:
            return int(au.get("input_tokens", 0) or 0), int(au.get("output_tokens", 0) or 0)
    return 0, 0


# ──────────────────────────────────────────────────────────────────────────────
# Aggregation — for the /api/budget endpoint
# ──────────────────────────────────────────────────────────────────────────────

def _period_start(period: Period) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_today - timedelta(days=now.weekday())
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=1)


async def get_summary(user_id: str, period: Period = "day") -> dict:
    """Return token + cost totals for `user_id` over the chosen period,
    plus a per-provider breakdown. Local models always show $0.0."""
    since = _period_start(period)
    async with async_session() as db:
        # Totals
        totals_q = select(
            func.coalesce(func.sum(UsageLog.input_tokens), 0),
            func.coalesce(func.sum(UsageLog.output_tokens), 0),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0.0),
            func.count(UsageLog.id),
        ).where(UsageLog.user_id == user_id, UsageLog.timestamp >= since)
        totals_row = (await db.execute(totals_q)).one()
        in_tok, out_tok, total_tok, cost, calls = totals_row

        # Per-provider breakdown
        by_provider_q = (
            select(
                UsageLog.provider,
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0),
                func.count(UsageLog.id),
            )
            .where(UsageLog.user_id == user_id, UsageLog.timestamp >= since)
            .group_by(UsageLog.provider)
        )
        per_provider = []
        for row in (await db.execute(by_provider_q)).all():
            prov, p_in, p_out, p_cost, p_calls = row
            per_provider.append({
                "provider": prov or "unknown",
                "input_tokens": int(p_in or 0),
                "output_tokens": int(p_out or 0),
                "cost_usd": round(float(p_cost or 0.0), 4),
                "calls": int(p_calls or 0),
            })

    return {
        "user_id": user_id,
        "period": period,
        "since": since.isoformat(),
        "input_tokens": int(in_tok or 0),
        "output_tokens": int(out_tok or 0),
        "total_tokens": int(total_tok or 0),
        "cost_usd": round(float(cost or 0.0), 4),
        "calls": int(calls or 0),
        "per_provider": per_provider,
    }
