# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_iteration.py
# @brief      Sprint 4b Phase 3.c — patch loop for failing candidate skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill iteration loop — Sprint 4b Phase 3.c.

When `skill_eval` returns `verdict=fail`, this module asks the
tier-S LLM to PATCH the playbook based on the judge's rationale +
the source failure cases. The new playbook replaces the candidate's
``content`` field and the ``iteration_count`` is bumped.

After ``MAX_ITERATIONS`` attempts without a pass, the candidate is
marked ``status=rejected`` (permanent failure record, kept for
audit). The whole loop is then driven by `skill_orchestrator.run_full_loop`.

Pattern d'inspiration : Hermes ``skill_manage(action='patch')``
(targeted find-and-replace style) + the iterate-on-fail loop
described in docs/external-references/hermes-skills-self-improvement.md §5.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillStatus
from app.services.learning.skill_creator import (
    _format_failure_case_for_prompt,
    parse_playbook_response,
)
from app.services.learning.tier_s import (
    estimate_cost_usd,
    get_tier_s_llm,
    record_tier_s_usage,
)

logger = logging.getLogger(__name__)


MAX_ITERATIONS = 5


# ── Prompts ─────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are ELY's autonomous skill PATCHER. A previous playbook you (or
another writer) drafted was just rejected by an external judge. Your
job is to rewrite it so it would clear the judge's objection on the
next pass.

Inputs you receive
------------------
1. The CURRENT playbook (Markdown + YAML frontmatter)
2. The JUDGE'S RATIONALE for the previous fail (1 sentence, specific)
3. The SAME source failure cases the playbook is supposed to address

Strict output contract
----------------------
Reply with EXACTLY a Markdown block starting with `---` (YAML
frontmatter) and finishing with the standard sections. NO other text
before or after. Same schema as the original:

```
---
name: kebab-case-slug-max-64-chars
description: One sentence ≤200 chars describing when this playbook applies.
tags: [list, of, 1-5, tags]
---

# Title (short noun phrase)

## When this applies
1-3 bullets describing the trigger pattern.

## Procedure
Numbered steps the agent must follow.

## What NOT to do
Bullets of forbidden moves (the actual failure modes from the cases).
```

How to patch
------------
- Address the judge's rationale DIRECTLY. If it said "too vague",
  name the actual tools. If it said "wrong layer", switch from tool
  proposal to procedure description. If it said "could make things
  worse", remove the dangerous step.
- KEEP the same `name` slug (so downstream linking stays stable).
- BIAS for shorter and more concrete over longer and more general.
- Tight: < 300 words total.
"""


def _compose_patch_prompt(
    skill: LearnedSkill, cases: list[FailureCase], judge_rationale: str,
) -> str:
    head = "CURRENT PLAYBOOK (to be patched)\n================================\n"
    head += f"--- frontmatter ---\nname: {skill.name}\n"
    head += f"description: {skill.description}\n--- body ---\n"
    head += skill.content
    head += "\n\nJUDGE'S RATIONALE FOR THE PREVIOUS FAIL\n"
    head += "=======================================\n"
    head += judge_rationale or "(no rationale supplied — assume the playbook was generic or off-target)"
    head += "\n\nSOURCE FAILURE CASES (unchanged from the original draft)\n"
    head += "========================================================\n"
    head += "\n\n".join(_format_failure_case_for_prompt(fc) for fc in cases[:5])
    head += (
        "\n\nNow output the patched playbook. ONLY the fenced markdown block "
        "with YAML frontmatter — no prose, no fences around the whole block."
    )
    return head


# ── Public API ──────────────────────────────────────────────────────────────


async def patch_skill(skill_id: str, judge_rationale: str) -> dict[str, Any]:
    """Run one patch pass on a candidate that just failed eval.

    Returns ::

        {
          "skill_id": "...",
          "status": "patched" | "skill_not_found" | "no_cases"
                    | "no_provider" | "llm_call_failed"
                    | "parse_failed" | "max_iterations_reached",
          "iteration_count": <int>,  # after the bump
          "provider_pick": "primary" | "fallback" | None,
          "tokens_in": <int>, "tokens_out": <int>,
          "estimated_cost_usd": <float>,
        }

    Side effect : on success, `LearnedSkill.content`,
    `frontmatter_json`, and `iteration_count` are updated in DB.
    `last_eval_score` is reset to None so the next call to
    `evaluate_skill` knows it's a fresh state.
    """
    out: dict[str, Any] = {
        "skill_id": skill_id,
        "status": "pending",
        "iteration_count": None,
        "provider_pick": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
    }

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one_or_none()
        if skill is None:
            out["status"] = "skill_not_found"
            return out
        out["iteration_count"] = skill.iteration_count

        if skill.iteration_count >= MAX_ITERATIONS:
            out["status"] = "max_iterations_reached"
            return out

        try:
            case_ids = json.loads(skill.from_failure_case_ids or "[]")
        except Exception:
            case_ids = []
        if not case_ids:
            out["status"] = "no_cases"
            return out

        cases = (await db.execute(
            select(FailureCase).where(FailureCase.id.in_(case_ids[:5]))
        )).scalars().all()

    llm, pick = await get_tier_s_llm()
    if llm is None or pick == "none":
        out["status"] = "no_provider"
        return out
    out["provider_pick"] = pick

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_compose_patch_prompt(skill, list(cases), judge_rationale)),
        ]
        response = await llm.ainvoke(messages)
        raw = getattr(response, "content", "") or ""
    except Exception as exc:
        out["status"] = "llm_call_failed"
        logger.warning("skill_iteration: tier-S call failed for skill %s: %s", skill_id, exc)
        return out

    # Usage accounting
    try:
        usage_meta = getattr(response, "usage_metadata", None) or {}
        in_tokens = int(usage_meta.get("input_tokens") or 0)
        out_tokens = int(usage_meta.get("output_tokens") or 0)
        model_name = (
            getattr(response, "response_metadata", {}).get("model_name")
            or getattr(llm, "model", None)
            or "tier-s"
        )
    except Exception:
        in_tokens = out_tokens = 0
        model_name = "tier-s"

    if in_tokens or out_tokens:
        await record_tier_s_usage(
            user_id=skill.user_id,
            model=model_name,
            provider="anthropic" if pick == "primary" else "deepseek",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            purpose="skill_iteration",
        )
        out["tokens_in"] = in_tokens
        out["tokens_out"] = out_tokens
        out["estimated_cost_usd"] = estimate_cost_usd(model_name, in_tokens, out_tokens)

    parsed = parse_playbook_response(raw)
    if parsed is None:
        out["status"] = "parse_failed"
        logger.warning(
            "skill_iteration: patch response did not parse for skill %s — "
            "first 200 chars: %s",
            skill_id, raw[:200],
        )
        return out

    # Persist the patched content + bump iteration_count + reset eval score
    new_iter = skill.iteration_count + 1
    async with async_session() as db:
        await db.execute(
            update(LearnedSkill)
            .where(LearnedSkill.id == skill_id)
            .values(
                content=parsed["body"],
                description=parsed["description"],
                frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
                iteration_count=new_iter,
                last_eval_score=None,  # fresh state for the next evaluate_skill
            )
        )
        await db.commit()

    out["status"] = "patched"
    out["iteration_count"] = new_iter
    logger.info(
        "skill_iteration: patched skill %s (iteration %d)",
        skill_id, new_iter,
    )
    return out


async def mark_rejected(skill_id: str, reason: str | None = None) -> bool:
    """Mark a candidate as permanently rejected after the iteration
    loop gave up. Returns True if a row was updated, False otherwise."""
    try:
        async with async_session() as db:
            result = await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id == skill_id)
                .values(
                    status=SkillStatus.REJECTED,
                    rationale=(reason or "Rejected after MAX_ITERATIONS eval attempts")[:2000],
                )
            )
            await db.commit()
            return result.rowcount > 0
    except Exception as exc:
        logger.warning("skill_iteration: mark_rejected failed for %s: %s", skill_id, exc)
        return False
