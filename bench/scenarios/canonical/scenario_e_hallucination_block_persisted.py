# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_e_hallucination_block_persisted.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario E : ensure a
#             completion_guard hallucination block recorded via
#             record_hallucination_block lands in the
#             `hallucination_blocks` table with JSON-decoded patterns.
#
#             Sprint 3.7.3 J4 — retrofitted onto ``throwaway_user`` so the
#             bench is idempotent (the inline User row used to leak).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario E — hallucination block persistence."""
from __future__ import annotations

import json


NAME = "E — Hallucination block persisted"
DESCRIPTION = (
    "Records a synthetic completion_guard verdict and verifies the row "
    "lands in `hallucination_blocks` with JSON-decoded patterns + tools."
)


TAGS = ["shallow"]

async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.hallucination_block import HallucinationBlock
    from app.services.learning import record_hallucination_block
    from bench.scenarios._base import throwaway_user

    async with throwaway_user("bench_e") as uid:
        row_id = await record_hallucination_block(
            user_id=uid,
            conversation_id="bench-conv-e",
            model_used="gemma-4-e4b-it",
            tier_llm="A",
            matched_patterns=["fr.passive_past", "fr.first_person_past"],
            tools_invoked=["gmail_list_emails"],
            destructive_tools_invoked=[],
            reason="completion_claim_without_destructive_tool_call",
            original_response="C'est fait, j'ai supprimé les 12 mails.",
        )

        if row_id is None:
            return {"pass": False, "reason": "record_hallucination_block returned None"}

        async with async_session() as db:
            row = (await db.execute(
                select(HallucinationBlock).where(HallucinationBlock.id == row_id)
            )).scalar_one_or_none()

        if row is None:
            return {"pass": False, "reason": f"row id {row_id} not found"}

        patterns = json.loads(row.matched_patterns)
        tools = json.loads(row.tools_invoked)

        checks = {
            "user_id_match": row.user_id == uid,
            "model_used_match": row.model_used == "gemma-4-e4b-it",
            "tier_llm_match": row.tier_llm == "A",
            "patterns_decoded": patterns == ["fr.passive_past", "fr.first_person_past"],
            "tools_decoded": tools == ["gmail_list_emails"],
            "reason_match": row.reason == "completion_claim_without_destructive_tool_call",
            "original_response_kept": "supprimé" in (row.original_response or ""),
            "prompt_version_filled": bool(row.prompt_version),
        }
        failed = [k for k, v in checks.items() if not v]
        return {
            "pass": not failed,
            "checks": checks,
            "row_id": row_id,
            "failed_checks": failed,
        }
