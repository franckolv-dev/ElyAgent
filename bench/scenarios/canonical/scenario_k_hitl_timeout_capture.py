# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_k_hitl_timeout_capture.py
# @brief      Sprint 3.7.3 J3 — canonical scenario K : a *silent* HITL denial
#             (reason='timeout', the user never answered the confirmation) is
#             still persisted AND captured — a timed-out approval is a real
#             signal the skill_creator should learn from, not a no-op.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario K — HITL silent timeout denial → failure_case capture."""
from __future__ import annotations


NAME = "K — HITL timeout (silent) → failure_case"
DESCRIPTION = (
    "record_hitl_refusal(decision='deny', reason='timeout') — the user never "
    "answered the prompt. The row persists with reason='timeout' and still "
    "produces a failure_cases row (capture is not gated on a user reason)."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning.failure_capture import SIGNAL_HITL_REFUSAL
    from app.services.learning.signals import record_hitl_refusal
    from bench.scenarios._base import from_checks, throwaway_user

    async with throwaway_user("bench_hitl_timeout") as uid:
        signal_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id="bench-conv-k",
            tool_name="calendar_delete_event",
            args={"event_id": "evt_123"},
            action_description="Supprimer l'événement « Réunion budget »",
            decision="deny",
            reason="timeout",
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

        checks = {
            "refusal_persisted": refusal is not None,
            "reason_is_timeout": refusal is not None and refusal.reason == "timeout",
            "silent_denial_still_captured": fc is not None,
            "failure_case_links_signal": fc is not None and fc.signal_id == signal_id,
        }
        return from_checks(checks, signal_id=signal_id)
