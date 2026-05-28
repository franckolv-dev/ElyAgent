# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_orchestrator.py
# @brief      Sprint 4b Phase 3.c — chain create→eval→iterate→reject
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill orchestrator — Sprint 4b Phase 3.c.

Single entry point that chains the three Phase-3 services :

    creator (3.a)  →  draft a candidate per cluster
        ↓
    eval (3.b)     →  judge each candidate
        ↓
    iterate (3.c)  →  if fail, patch and re-judge
        ↓
    reject (3.c)   →  if still failing after MAX_ITERATIONS, mark rejected

Public entry point :
    `run_full_loop(user_id, batch_size=3, max_iterations=5)`

This is what the admin endpoint (`POST /admin/learning/skill-creator/run`)
calls. It's also what a future cron job will call.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.learning.skill_creator import run_skill_creator_batch
from app.services.learning.skill_eval import evaluate_skill
from app.services.learning.skill_iteration import (
    MAX_ITERATIONS,
    mark_rejected,
    patch_skill,
)

logger = logging.getLogger(__name__)


# Statuses returned by `evaluate_skill` that should NOT trigger a patch
# attempt (they indicate a transient or infrastructural problem, not a
# weak playbook). On these, the loop exits early for the cluster.
_NON_RECOVERABLE_EVAL_STATUSES = {
    "no_provider",
    "llm_call_failed",
    "parse_failed",
    "skill_not_found",
    "no_cases",
}


async def _evaluate_until_done(
    skill_id: str, max_iterations: int,
) -> dict[str, Any]:
    """Run evaluate → patch → re-evaluate until pass / max / unrecoverable.

    Returns the loop summary for one skill ::

        {
          "skill_id": "...",
          "iterations_used": <int>,
          "final_status": "pass" | "rejected" | "no_provider"
                          | "llm_call_failed" | "parse_failed",
          "final_score": <int or None>,
          "evals": [<list of evaluate_skill dicts>],
          "patches": [<list of patch_skill dicts>],
        }
    """
    summary: dict[str, Any] = {
        "skill_id": skill_id,
        "iterations_used": 0,
        "final_status": None,
        "final_score": None,
        "evals": [],
        "patches": [],
    }

    cap = max(1, min(int(max_iterations or MAX_ITERATIONS), MAX_ITERATIONS))

    for attempt in range(cap):
        eval_result = await evaluate_skill(skill_id)
        summary["evals"].append(eval_result)

        status = eval_result.get("status")
        if status in _NON_RECOVERABLE_EVAL_STATUSES:
            summary["final_status"] = status
            summary["final_score"] = eval_result.get("score")
            return summary

        if status == "evaluated":
            summary["final_score"] = eval_result.get("score")
            if eval_result.get("verdict") == "pass":
                summary["final_status"] = "pass"
                return summary
            # verdict=fail → maybe iterate. Don't patch on the last
            # attempt — there's no point spending tokens on a patch
            # we wouldn't re-evaluate.
            if attempt < cap - 1:
                rationale = eval_result.get("rationale") or ""
                patch_result = await patch_skill(skill_id, rationale)
                summary["patches"].append(patch_result)
                if patch_result.get("status") != "patched":
                    # Patching failed (parse / provider / etc.) — stop
                    # the loop and record what happened.
                    summary["final_status"] = (
                        "patch_" + str(patch_result.get("status", "failed"))
                    )
                    return summary
                summary["iterations_used"] = patch_result.get(
                    "iteration_count", attempt + 2,
                )
                # Loop continues — next iteration will re-evaluate.
                continue

    # Reached cap without pass — mark rejected
    summary["final_status"] = "rejected"
    last_eval = summary["evals"][-1] if summary["evals"] else None
    reason = (
        f"Rejected after {cap} eval attempts. Last score: "
        f"{(last_eval or {}).get('score')}. "
        f"Last rationale: {(last_eval or {}).get('rationale', '(none)')}"
    )
    await mark_rejected(skill_id, reason)
    return summary


async def run_full_loop(
    *,
    user_id: str,
    batch_size: int = 3,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    """Run one full batch of create → eval → iterate for a user.

    Returns ::

        {
          "user_id": "...",
          "batch_size": <int>,
          "max_iterations": <int>,
          "creator": {<run_skill_creator_batch result>},
          "loops": [<one _evaluate_until_done summary per drafted skill>],
          "totals": {
            "drafts": <int>,
            "passed": <int>,
            "rejected": <int>,
            "errored": <int>,
          },
        }

    Never raises. Per-skill failures are recorded in the loops array
    rather than aborting the batch.
    """
    if not user_id:
        return {
            "error": "user_id is required",
            "totals": {"drafts": 0, "passed": 0, "rejected": 0, "errored": 0},
            "loops": [],
        }

    creator_result = await run_skill_creator_batch(
        user_id=user_id, batch_size=batch_size,
    )

    loops: list[dict[str, Any]] = []
    passed = rejected = errored = 0

    for draft in creator_result.get("drafts", []):
        if draft.get("status") != "drafted":
            # Creator-level failure (parse_failed / no_provider / etc.)
            # — nothing to evaluate.
            loops.append({
                "draft_status": draft.get("status"),
                "skill_id": None,
                "final_status": draft.get("status"),
            })
            errored += 1
            continue

        skill_id = draft.get("learned_skill_id")
        loop_result = await _evaluate_until_done(skill_id, max_iterations)
        loop_result["skill_name"] = draft.get("skill_name")
        loop_result["draft_status"] = "drafted"
        loops.append(loop_result)

        if loop_result["final_status"] == "pass":
            passed += 1
        elif loop_result["final_status"] == "rejected":
            rejected += 1
        else:
            errored += 1

    return {
        "user_id": user_id,
        "batch_size": batch_size,
        "max_iterations": max_iterations,
        "creator": creator_result,
        "loops": loops,
        "totals": {
            "drafts": creator_result.get("skills_created", 0),
            "passed": passed,
            "rejected": rejected,
            "errored": errored,
        },
    }
