# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tier_s.py
# @brief      Sprint 4b Phase 2 + Backlog #19 — Tier S provider chain
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Tier S — dedicated LLM lane for skill creation + iteration.

Distinct from the user-facing tiers A/B/C/IMG/MAINTENANCE. Used by the
skill_creator + skill_eval + skill_iteration services. Carries its own
monthly budget cap because the providers in the chain (Opus 4.5,
Mistral Large 3) are expensive: 5 iterations × ~10k tokens each can
add up to 1-2€ per skill candidate, and we don't want this hitting
the same routing caches as conversational tier C.

Provider chain (configurable, Backlog #19 promoted 2026-05-29)
--------------------------------------------------------------
Set `LLM_TIER_S_CHAIN` env var to a comma-separated list of provider
names, tried in order, first available wins:

  LLM_TIER_S_CHAIN=mistral,anthropic,deepseek   # EU-first, perf, fallback
  LLM_TIER_S_CHAIN=anthropic                      # perf-only
  LLM_TIER_S_CHAIN=deepseek                       # cost-only
  LLM_TIER_S_CHAIN=mistral,deepseek               # full sovereignty + cost

Default chain (backward compat with the pre-backlog-19 hardcoded shape) :
  LLM_TIER_S_CHAIN=anthropic,deepseek

Per-provider rationale
----------------------
- **anthropic** (Claude Opus 4.5) — best for iterative code/playbook
  generation, prompt-caching enabled, but $$$.
- **mistral** (Mistral Large 3) — EU sovereignty (Paris-hosted), strong
  on French content (the playbooks Opus tends to anglicise), 7-12×
  cheaper than Opus per million tokens. The default option for users
  who want strict EU-only.
- **deepseek** (DeepSeek v4-pro reasoner) — extremely cheap fallback,
  good code generation, OpenAI-compatible API.

The provider name returned by `get_tier_s_llm` is the SHORT NAME (one
of "anthropic", "mistral", "deepseek", "none"). Callers pass it
verbatim as the `provider` field of `record_tier_s_usage`.

Spending is recorded in the existing `usage_logs` table with
`skill_used = "tier_s.<purpose>"` so the budget query reuses the same
audit surface as user-facing LLM calls. Reset of the monthly budget
is implicit (we sum over the current calendar month).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select

from app.database import async_session

logger = logging.getLogger(__name__)


# ── Defaults (overridable by env) ───────────────────────────────────────────

_DEFAULT_OPUS_MODEL = "claude-opus-4-5"
_DEFAULT_MISTRAL_MODEL = "mistral-large-latest"
_DEFAULT_DEEPSEEK_MODEL = "deepseek-reasoner"

# Default chain — backward compat with pre-backlog-19 (Opus → DeepSeek).
# Override via `LLM_TIER_S_CHAIN=mistral,anthropic,deepseek` for full
# EU-first sovereignty.
_DEFAULT_CHAIN = "anthropic,deepseek"

DEFAULT_MONTHLY_BUDGET_USD = 50.0


# ── Rough cost table (USD per million tokens, input / output) ──────────────
# Numbers from official pricing pages at end-2025; admin can override the
# whole dict via the future settings UI if pricing shifts. Keys are
# prefixes so any "claude-opus-*" variant maps to the same rate.
_COST_PER_MTOKEN_USD: dict[str, tuple[float, float]] = {
    "claude-opus":       (15.00, 75.00),
    "claude-sonnet":     ( 3.00, 15.00),  # kept for completeness, not in default chain
    "mistral-large":     ( 2.00,  6.00),  # 7-12× cheaper than Opus — the budget argument
    "deepseek-reasoner": ( 0.55,  2.19),
    "deepseek-chat":     ( 0.27,  1.10),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of a tier-S call from token counts.

    Linear lookup against `_COST_PER_MTOKEN_USD` by model-name prefix.
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
    """Monthly cap from env. `<= 0` means no cap (allow forever)."""
    raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_USD")
    if raw is None:
        raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_EUR")  # parity ≈ 1:1, either accepted
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

    Treats cap `<= 0` as "disabled" (always allow primary).

    Naming kept for backwards compat (Phase 2 callers + tests). The
    semantics are now : "are we allowed to attempt the first provider
    in the chain, or should we skip straight to the fallback(s)?".
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
    """Persist one tier-S call in `usage_logs`.

    `purpose` is appended to `"tier_s."` to form the `skill_used`
    discriminator (e.g. `"tier_s.skill_creator"`).

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


# ── Provider builders ───────────────────────────────────────────────────────
# One builder per provider name. Returns the LangChain ChatModel
# instance, or None if the provider can't be built (missing API key,
# import failure, etc.). Builders are pure — they don't touch DB or
# spend tracking.


def _build_opus() -> Any | None:
    """Claude Opus 4.5 via langchain-anthropic, prompt-caching enabled."""
    try:
        from langchain_anthropic import ChatAnthropic
        from app.config import get_settings
        from app.services.llm_provider import get_runtime_key

        api_key = get_runtime_key("anthropic") or get_settings().anthropic_api_key
        if not api_key:
            return None

        model = os.getenv("LLM_TIER_S_OPUS_MODEL", _DEFAULT_OPUS_MODEL)
        # Backwards compat: old env name also accepted.
        if model == _DEFAULT_OPUS_MODEL:
            model = os.getenv("LLM_TIER_S_PRIMARY_MODEL", model)
        max_tokens = int(os.getenv("LLM_TIER_S_MAX_TOKENS", "8192"))

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=0.2,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
            },
        )
    except Exception as exc:
        logger.warning("tier_s: failed to build Opus (%s)", exc)
        return None


def _build_mistral_large() -> Any | None:
    """Mistral Large 3 via langchain-mistralai — EU sovereignty,
    7-12× cheaper than Opus. Default choice for users who want strict
    EU-only processing of their learning signals."""
    try:
        from langchain_mistralai import ChatMistralAI
        from app.config import get_settings
        from app.services.llm_provider import get_runtime_key

        api_key = get_runtime_key("mistral") or get_settings().mistral_api_key
        if not api_key:
            return None

        model = os.getenv("LLM_TIER_S_MISTRAL_MODEL", _DEFAULT_MISTRAL_MODEL)
        max_tokens = int(os.getenv("LLM_TIER_S_MAX_TOKENS", "8192"))

        return ChatMistralAI(
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("tier_s: failed to build Mistral Large (%s)", exc)
        return None


def _build_deepseek() -> Any | None:
    """DeepSeek v4-pro reasoner via OpenAI-compatible endpoint — cheap,
    solid on code, good fallback when budget tightens or other
    providers are down."""
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
            return None

        model = os.getenv("LLM_TIER_S_DEEPSEEK_MODEL", _DEFAULT_DEEPSEEK_MODEL)
        # Backwards compat: old env name also accepted.
        if model == _DEFAULT_DEEPSEEK_MODEL:
            model = os.getenv("LLM_TIER_S_FALLBACK_MODEL", model)
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
        logger.warning("tier_s: failed to build DeepSeek (%s)", exc)
        return None


# Backwards-compat alias retained so Phase 2 tests/imports still work.
# Internal callers use the new `_build_opus` directly.
def _build_primary() -> Any | None:
    return _build_opus()


def _build_fallback() -> Any | None:
    return _build_deepseek()


# Canonical name returned to callers — collapses aliases so analytics
# (UsageLog.provider) don't fork. Users can type "opus" / "claude" /
# "anthropic" interchangeably in `LLM_TIER_S_CHAIN`.
_PROVIDER_CANONICAL: dict[str, str] = {
    "anthropic": "anthropic",
    "opus":      "anthropic",
    "claude":    "anthropic",
    "mistral":   "mistral",
    "deepseek":  "deepseek",
}

# Canonical name → builder-attribute-name on THIS module. Looked up
# late-bound via `getattr(sys.modules[__name__], attr)` in `_dispatch`
# so tests can monkeypatch the `_build_*` attributes and the chain
# picks up the new function. A static dict that captured the function
# objects at module-load would freeze the original bindings forever.
_BUILDER_ATTRS: dict[str, str] = {
    "anthropic": "_build_opus",
    "mistral":   "_build_mistral_large",
    "deepseek":  "_build_deepseek",
}


def _dispatch_build(canonical_name: str) -> Any | None:
    """Late-bound provider build — re-reads the module attribute each
    time so monkeypatch in tests actually swaps the implementation."""
    import sys
    attr = _BUILDER_ATTRS.get(canonical_name)
    if attr is None:
        return None
    builder = getattr(sys.modules[__name__], attr, None)
    if builder is None:
        return None
    try:
        return builder()
    except Exception as exc:
        logger.warning("tier_s: builder %s raised (%s)", attr, exc)
        return None


def _parse_chain() -> list[str]:
    """Read `LLM_TIER_S_CHAIN` env and normalise to a list of canonical
    provider names. Unknown names are dropped with a warning."""
    raw = os.getenv("LLM_TIER_S_CHAIN", _DEFAULT_CHAIN)
    out: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        canonical = _PROVIDER_CANONICAL.get(name)
        if canonical is None:
            logger.warning("tier_s: unknown provider %r in LLM_TIER_S_CHAIN — skipping", name)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


# Type alias for callers — the pick is now the canonical provider name
# (or "none"). Phase 2 callers checked `pick == "none"` only — that
# contract is preserved.
TierSPick = str


async def get_tier_s_llm(*, force_fallback: bool = False) -> tuple[Any | None, TierSPick]:
    """Iterate the configured provider chain and return `(llm, pick)`.

    Returns the FIRST chain item whose builder succeeds AND whose
    selection respects the budget cap. The `pick` string is the
    canonical provider name (or `"none"` if nothing was buildable).

    `force_fallback=True` skips the FIRST item in the chain — useful
    when a caller wants to deliberately avoid the most-expensive
    provider (e.g. eval loop's deterministic re-runs).

    Budget rule (Phase 2 contract preserved): if the monthly spend is
    over the cap, the first chain item is skipped. Subsequent items
    are still attempted. This means a chain of `mistral,deepseek` with
    Mistral as the "primary" gets degraded to DeepSeek when budget
    runs out — not to nothing.
    """
    chain = _parse_chain()
    if not chain:
        logger.warning("tier_s: empty provider chain — nothing to attempt")
        return None, "none"

    within_budget = await is_primary_within_budget()
    skip_first = force_fallback or not within_budget

    for i, name in enumerate(chain):
        if i == 0 and skip_first and len(chain) > 1:
            # Skip the first provider — caller asked for fallback OR
            # the budget is exhausted for the primary. Single-item
            # chain has no alternative, so we don't skip.
            continue
        llm = _dispatch_build(name)
        if llm is not None:
            return llm, name
    logger.info("tier_s: every provider in chain %s is unavailable", chain)
    return None, "none"
