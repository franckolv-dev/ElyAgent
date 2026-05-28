# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_g_provider_switch_persisted.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario G : ensure a
#             fallback chain provider switch lands in `provider_switches`.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario G — provider switch persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import select


NAME = "G — Provider switch persisted"
DESCRIPTION = (
    "Records a synthetic fallback chain provider switch (deepseek pro → "
    "anthropic sonnet for tier C, timeout reason) and verifies the row "
    "lands in `provider_switches`."
)


async def run() -> dict:
    from app.database import async_session, init_db
    from app.models.provider_switch import ProviderSwitch
    from app.models.user import User
    from app.services.learning import record_provider_switch

    await init_db()

    uid = f"bench_g_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"bench_g_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()

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
