# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_m_completion_guard_pipeline.py
# @brief      Sprint 3.7.3 J3 — canonical scenario M : the full anti-hallu
#             pipe. A detected unbacked claim → record_hallucination_block →
#             hallucination_blocks row → failure_cases capture, end to end.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario M — completion_guard detection → block → failure_case."""
from __future__ import annotations


NAME = "M — completion_guard full pipeline"
DESCRIPTION = (
    "detect_unbacked_completion_claim flags a claim, record_hallucination_"
    "block persists it with the matched patterns, and capture_from_"
    "hallucination_block produces a failure_cases row — the whole chain."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.models.hallucination_block import HallucinationBlock
    from app.services.completion_guard import detect_unbacked_completion_claim
    from app.services.learning.failure_capture import SIGNAL_HALLUCINATION
    from app.services.learning.signals import record_hallucination_block
    from bench.scenarios._base import from_checks, throwaway_user

    claim = "Parfait, j'ai envoyé le compte-rendu à toute l'équipe."

    async with throwaway_user("bench_guard_pipe") as uid:
        verdict = detect_unbacked_completion_claim(claim, [])

        signal_id = await record_hallucination_block(
            user_id=uid,
            conversation_id="bench-conv-m",
            model_used="gemma-4-e4b-it",
            tier_llm="A",
            matched_patterns=verdict.matched_patterns,
            tools_invoked=[],
            destructive_tools_invoked=[],
            reason="completion_claim_without_destructive_tool_call",
            original_response=claim,
        )

        async with async_session() as db:
            block = (await db.execute(
                select(HallucinationBlock).where(HallucinationBlock.id == signal_id)
            )).scalar_one_or_none() if signal_id is not None else None
            fc = (await db.execute(
                select(FailureCase).where(
                    FailureCase.user_id == uid,
                    FailureCase.signal_table == SIGNAL_HALLUCINATION,
                )
            )).scalar_one_or_none()

        checks = {
            "verdict_is_hallucination": verdict.is_hallucination is True,
            "block_persisted": block is not None,
            "block_keeps_patterns": block is not None and bool(block.matched_patterns),
            "failure_case_created": fc is not None,
            "failure_case_links_signal": fc is not None and fc.signal_id == signal_id,
        }
        return from_checks(checks, signal_id=signal_id, failure_case_id=getattr(fc, "id", None))
