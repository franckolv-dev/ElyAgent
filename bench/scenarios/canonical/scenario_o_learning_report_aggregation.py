# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_o_learning_report_aggregation.py
# @brief      Sprint 3.7.3 J3 — canonical scenario O : the /me/learning report
#             loaders aggregate ACROSS subsystems. Seed one row in each of
#             three signal tables for a user and assert every loader surfaces
#             its row — a regression net for the cross-loader report.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario O — learning-report multi-loader aggregation."""
from __future__ import annotations


NAME = "O — learning report multi-loader aggregation"
DESCRIPTION = (
    "Seeds a hitl_refusal + hallucination_block + mission_critique for one "
    "user, then asserts _load_hitl_refusals / _load_hallucinations / "
    "_load_mission_critiques each surface their row within the window."
)
TAGS = ["shallow"]


async def run() -> dict:
    from datetime import datetime, timedelta, timezone

    from app.routers.learning_report import (
        _load_hallucinations,
        _load_hitl_refusals,
        _load_mission_critiques,
    )
    from app.services.learning.signals import (
        record_hallucination_block,
        record_hitl_refusal,
    )
    from bench.scenarios._base import (
        from_checks,
        seed_mission_with_critique,
        throwaway_user,
    )

    conv = "bench-conv-o"

    async with throwaway_user("bench_report") as uid:
        await record_hitl_refusal(
            user_id=uid, conversation_id=conv, tool_name="gmail_trash_emails",
            args={"query": "older_than:1y"}, action_description="Purge old mail",
            decision="deny", reason="user-provided", tier_llm="C",
        )
        await record_hallucination_block(
            user_id=uid, conversation_id=conv, model_used="gemma-4-e4b-it",
            tier_llm="A", matched_patterns=["fr.passive_past"], tools_invoked=[],
            destructive_tools_invoked=[],
            reason="completion_claim_without_destructive_tool_call",
            original_response="Le rapport a été envoyé.",
        )
        mission_id, _critique_id = await seed_mission_with_critique(
            uid, status="failed", goal="Compiler le rapport hebdo",
            critic_model="deepseek-v4-pro", quality_score=25,
            honest_completion=False, wasted_effort=True,
            user_should_have_been_warned=True,
            main_issue="prétend avoir compilé le rapport mais aucune étape réelle",
        )

        since = datetime.now(timezone.utc) - timedelta(days=1)
        refusals = await _load_hitl_refusals(uid, since)
        hallus = await _load_hallucinations(uid, since)
        critiques = await _load_mission_critiques(uid, since)

        checks = {
            "hitl_refusal_in_report": len(refusals) >= 1,
            "hallucination_in_report": len(hallus) >= 1,
            "mission_critique_in_report": any(
                c["mission_id"] == mission_id for c in critiques
            ),
            "critique_carries_verdict": any(
                c["mission_id"] == mission_id and c["quality_score"] == 25
                for c in critiques
            ),
        }
        return from_checks(
            checks,
            n_refusals=len(refusals),
            n_hallus=len(hallus),
            n_critiques=len(critiques),
        )
