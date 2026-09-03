# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_h_prompt_version_chain.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario H : ensure
#             `prompt_version` propagates from the live _SYSTEM_PROMPT_BASE
#             hash to every recorded signal. Catches drift if the helper
#             is bypassed by a future writer.
#
#             Sprint 3.7.3 J4 — retrofitted onto ``throwaway_user`` so the
#             bench is idempotent (the inline User row used to leak).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario H — prompt_version chain."""
from __future__ import annotations


NAME = "H — prompt_version chain"
DESCRIPTION = (
    "Verifies the prompt_version of newly recorded signals matches the "
    "live `current_system_prompt_version()` — i.e. nobody short-circuits "
    "the helper."
)


TAGS = ["shallow"]

async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.hitl_refusal import HitlRefusal
    from app.models.provider_switch import ProviderSwitch
    from app.services.learning import (
        current_system_prompt_version,
        record_hitl_refusal,
        record_provider_switch,
    )
    from bench.scenarios._base import throwaway_user

    expected = current_system_prompt_version()
    if not expected or len(expected) != 8:
        return {
            "pass": False,
            "reason": f"current_system_prompt_version() returned bogus value: {expected!r}",
        }

    async with throwaway_user("bench_h") as uid:
        hitl_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id="bench-conv-h",
            tool_name="some_tool",
            args={},
            action_description="action",
            decision="deny",
            reason="user-provided",
        )
        switch_id = await record_provider_switch(
            user_id=uid,
            conversation_id="bench-conv-h",
            tier_llm="B",
            from_provider="p1",
            to_provider="p2",
            reason="timeout",
            position_in_chain=1,
        )

        async with async_session() as db:
            hitl = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.id == hitl_id)
            )).scalar_one_or_none()
            switch = (await db.execute(
                select(ProviderSwitch).where(ProviderSwitch.id == switch_id)
            )).scalar_one_or_none()

        checks = {
            "expected_hash_8_hex": len(expected) == 8 and all(
                c in "0123456789abcdef" for c in expected
            ),
            "hitl_row_prompt_version_match": hitl is not None and hitl.prompt_version == expected,
            "switch_row_prompt_version_match": switch is not None and switch.prompt_version == expected,
        }
        failed = [k for k, v in checks.items() if not v]
        return {
            "pass": not failed,
            "checks": checks,
            "expected_hash": expected,
            "hitl_prompt_version": hitl.prompt_version if hitl else None,
            "switch_prompt_version": switch.prompt_version if switch else None,
            "failed_checks": failed,
        }
