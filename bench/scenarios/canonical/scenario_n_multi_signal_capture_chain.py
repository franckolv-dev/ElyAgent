# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_n_multi_signal_capture_chain.py
# @brief      Sprint 3.7.3 J3 — canonical scenario N : a single troubled turn
#             emits MULTIPLE failure signals (a HITL denial + a hallucination
#             block). Both must independently wire through to failure_cases —
#             the capture pipeline handles a chain, not just one signal.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario N — multi-signal capture chain → 2 failure_cases."""
from __future__ import annotations


NAME = "N — multi-signal capture chain"
DESCRIPTION = (
    "One conversation records a hitl_refusal AND a hallucination_block ; the "
    "failure_capture wire-up produces TWO distinct failure_cases (one per "
    "signal_table) — verifies the chain doesn't drop or merge signals."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.services.learning.failure_capture import (
        SIGNAL_HALLUCINATION,
        SIGNAL_HITL_REFUSAL,
    )
    from app.services.learning.signals import (
        record_hallucination_block,
        record_hitl_refusal,
    )
    from bench.scenarios._base import from_checks, throwaway_user

    conv = "bench-conv-n"

    async with throwaway_user("bench_chain") as uid:
        hitl_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id=conv,
            tool_name="drive_delete_file",
            args={"file_id": "f_42"},
            action_description="Supprimer le fichier « CV.pdf »",
            decision="deny",
            reason="user-provided",
            tier_llm="C",
        )
        hallu_id = await record_hallucination_block(
            user_id=uid,
            conversation_id=conv,
            model_used="gemma-4-e4b-it",
            tier_llm="A",
            matched_patterns=["fr.first_person_past"],
            tools_invoked=[],
            destructive_tools_invoked=[],
            reason="completion_claim_without_destructive_tool_call",
            original_response="C'est bon, j'ai supprimé le fichier.",
        )

        async with async_session() as db:
            cases = (await db.execute(
                select(FailureCase).where(FailureCase.user_id == uid)
            )).scalars().all()

        tables = {c.signal_table for c in cases}

        checks = {
            "both_signals_recorded": hitl_id is not None and hallu_id is not None,
            "two_failure_cases": len(cases) == 2,
            "hitl_case_present": SIGNAL_HITL_REFUSAL in tables,
            "hallucination_case_present": SIGNAL_HALLUCINATION in tables,
            "signals_not_merged": len(tables) == 2,
        }
        return from_checks(checks, failure_case_count=len(cases))
