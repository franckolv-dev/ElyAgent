# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_creator.py
# @brief      Sprint 4b V2 J6c — generate→validate→iterate→persist loop for
#             auto-developed Python @tool skills.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""The V2 analog of ``skill_creator`` (design note J0).

Ties the generator (``tool_generator``) and the validation chain
(``tool_orchestrator``) into one self-correcting loop:

    generate → validate (5 stages) → if it fails, feed the exact failure
    back into the generator → retry, up to ``max_iterations`` → on success,
    persist a ``LearnedSkill(content_format=python_tool, status=candidate)``
    carrying the full validation report.

It NEVER auto-activates anything: the output is always a ``candidate``
awaiting HITL admin promotion (which, plus the live bind, is J7). The
tier-S model is whatever ``LLM_TIER_S_CHAIN`` selects (see tool_generator).

``smoke_kwargs`` is an optional sample input for stage 4; when absent the
smoke stage is skipped (we can't call the function without arguments).
The trigger source (a failure_case / admin request) should supply one.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.database import async_session
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning.tool_generator import generate_tool_source
from app.services.learning.tool_orchestrator import validate_tool_source

logger = logging.getLogger(__name__)

# Generator statuses that won't improve on retry — stop the loop.
_TERMINAL_GEN_STATUSES = {"no_provider", "llm_call_failed"}


def _existing_tool_names() -> set[str]:
    """Names of all registered tools — for the collision check. Best-effort."""
    try:
        from app.skills.registry import get_skill_registry

        return set(get_skill_registry().all_tool_names())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tool_creator: registry name lookup failed (%s)", exc)
        return set()


async def generate_and_persist_tool(
    *,
    task_description: str,
    user_id: str,
    smoke_kwargs: dict | None = None,
    max_iterations: int = 3,
    existing_names: set[str] | None = None,
    from_failure_case_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Run the generate→validate→iterate→persist loop once.

    Returns a summary dict ::

        {
          "status": "created" | "validation_failed" | "no_provider" | "error",
          "tool_name": "...",            # when created
          "learned_skill_id": "...",     # when created
          "iterations": 2,
          "attempts": [ {iteration, gen_status, validation} , ... ],
        }

    Best-effort: never raises. On success, persists a candidate skill.
    """
    if not user_id:
        return {"status": "error", "error": "user_id is required", "attempts": []}

    max_iterations = max(1, min(int(max_iterations or 1), 5))
    names = existing_names if existing_names is not None else _existing_tool_names()
    run_smoke = smoke_kwargs is not None

    attempts: list[dict[str, Any]] = []
    prior_errors: str | None = None

    for i in range(1, max_iterations + 1):
        source, gen_info = await generate_tool_source(
            task_description=task_description,
            user_id=user_id,
            prior_errors=prior_errors,
        )
        attempt: dict[str, Any] = {"iteration": i, "gen_status": gen_info.get("status")}

        if source is None:
            attempt["error"] = gen_info.get("error") or gen_info.get("raw_excerpt", "")
            attempts.append(attempt)
            if gen_info.get("status") in _TERMINAL_GEN_STATUSES:
                return {
                    "status": gen_info.get("status"),
                    "iterations": i,
                    "attempts": attempts,
                }
            # parse failure → nudge and retry
            prior_errors = "Your reply did not contain a valid Python code block."
            continue

        report = validate_tool_source(
            source,
            existing_names=names,
            smoke_kwargs=smoke_kwargs,
            run_smoke=run_smoke,
        )
        attempt["validation"] = report.summary()
        attempt["tool_name"] = report.tool_name
        attempts.append(attempt)

        if not report.ok:
            prior_errors = report.summary()
            continue

        # ── success → persist a candidate ──────────────────────────────
        skill = LearnedSkill(
            user_id=user_id,
            name=(report.tool_name or "generated_tool")[:64],
            description=task_description.strip()[:1024],
            content=source,
            content_format=SkillContentFormat.PYTHON_TOOL,
            frontmatter_json=json.dumps(
                {"tool_name": report.tool_name, "provider": gen_info.get("provider_pick")},
                ensure_ascii=False,
            ),
            validation_report_json=report.to_json(),
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=i,
            from_failure_case_ids=json.dumps(from_failure_case_ids or [], ensure_ascii=False),
            rationale=(
                f"Auto-generated python_tool for: {task_description.strip()[:300]} "
                f"(validated through {i} iteration(s), provider={gen_info.get('provider_pick')})."
            ),
        )
        async with async_session() as db:
            db.add(skill)
            await db.flush()
            skill_id = skill.id
            await db.commit()
        logger.info(
            "tool_creator: created candidate python_tool %s (%s) in %d iteration(s)",
            skill_id, report.tool_name, i,
        )
        return {
            "status": "created",
            "tool_name": report.tool_name,
            "learned_skill_id": skill_id,
            "iterations": i,
            "attempts": attempts,
        }

    # exhausted without a passing candidate
    return {
        "status": "validation_failed",
        "iterations": len(attempts),
        "attempts": attempts,
    }
