# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_j_hitl_refusal_capture.py
# @brief      Sprint 3.7.3 J3 — canonical scenario J : a user-provided HITL
#             denial persists a hitl_refusals row AND wires through to a
#             failure_cases row for the skill_creator (deny_with_reason).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario J — HITL denial (user-provided) → failure_case capture."""
from __future__ import annotations


NAME = "J — HITL refusal (user-provided) → failure_case"
DESCRIPTION = (
    "record_hitl_refusal(decision='deny', reason='user-provided') persists "
    "the hitl_refusals row and triggers capture_from_hitl_refusal → a "
    "failure_cases row with signal_table='hitl_refusals' + stable hash."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning.failure_capture import (
        SIGNAL_HITL_REFUSAL,
        _fingerprint,
    )
    from app.services.learning.signals import record_hitl_refusal
    from bench.scenarios._base import from_checks, throwaway_user

    tool_name = "gmail_trash_emails"
    decision = "deny"

    async with throwaway_user("bench_hitl_deny") as uid:
        signal_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id="bench-conv-j",
            tool_name=tool_name,
            args={"query": "from:newsletter"},
            action_description="Mettre 12 newsletters à la corbeille",
            decision=decision,
            reason="user-provided",
            tier_llm="C",
        )

        async with async_session() as db:
            refusal = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.id == signal_id)
            )).scalar_one_or_none() if signal_id is not None else None
            fc = (await db.execute(
                select(FailureCase).where(
                    FailureCase.user_id == uid,
                    FailureCase.signal_table == SIGNAL_HITL_REFUSAL,
                )
            )).scalar_one_or_none()

        expected_fp = _fingerprint(SIGNAL_HITL_REFUSAL, tool_name, decision)

        checks = {
            "refusal_persisted": refusal is not None,
            "decision_match": refusal is not None and refusal.decision == decision,
            "failure_case_created": fc is not None,
            "failure_case_links_signal": fc is not None and fc.signal_id == signal_id,
            "pattern_hash_stable": fc is not None and fc.pattern_hash == expected_fp,
        }
        return from_checks(checks, signal_id=signal_id, failure_case_id=getattr(fc, "id", None))
