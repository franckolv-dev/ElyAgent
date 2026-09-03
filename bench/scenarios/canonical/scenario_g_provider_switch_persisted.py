# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_g_provider_switch_persisted.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario G : ensure a
#             fallback chain provider switch lands in `provider_switches`.
#
#             Sprint 3.7.3 J4 — retrofitted onto ``throwaway_user`` so the
#             bench is idempotent (the inline User row used to leak).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario G — provider switch persistence."""
from __future__ import annotations


NAME = "G — Provider switch persisted"
DESCRIPTION = (
    "Records a synthetic fallback chain provider switch (deepseek pro → "
    "anthropic sonnet for tier C, timeout reason) and verifies the row "
    "lands in `provider_switches`."
)


TAGS = ["shallow"]

async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.provider_switch import ProviderSwitch
    from app.services.learning import record_provider_switch
    from bench.scenarios._base import throwaway_user

    async with throwaway_user("bench_g") as uid:
        row_id = await record_provider_switch(
            user_id=uid,
            conversation_id="bench-conv-g",
            tier_llm="C",
            from_provider="deepseek-v4-pro",
            to_provider="anthropic-sonnet",
            reason="timeout",
            position_in_chain=2,
        )

        if row_id is None:
            return {"pass": False, "reason": "record_provider_switch returned None"}

        async with async_session() as db:
            row = (await db.execute(
                select(ProviderSwitch).where(ProviderSwitch.id == row_id)
            )).scalar_one_or_none()

        if row is None:
            return {"pass": False, "reason": f"row id {row_id} not found"}

        checks = {
            "user_id_match": row.user_id == uid,
            "tier_llm_match": row.tier_llm == "C",
            "from_provider_match": row.from_provider == "deepseek-v4-pro",
            "to_provider_match": row.to_provider == "anthropic-sonnet",
            "reason_match": row.reason == "timeout",
            "position_in_chain_match": row.position_in_chain == 2,
            "prompt_version_filled": bool(row.prompt_version),
        }
        failed = [k for k, v in checks.items() if not v]
        return {
            "pass": not failed,
            "checks": checks,
            "row_id": row_id,
            "failed_checks": failed,
        }
