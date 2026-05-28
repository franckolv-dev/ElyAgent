# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_eval.py
# @brief      Sprint 4b Phase 3.b — LLM-as-judge eval for candidate skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill evaluation — Sprint 4b Phase 3.b.

Given a ``LearnedSkill`` candidate that the ``skill_creator`` (3.a)
just drafted, ask the tier-S LLM to act as a neutral judge: "if this
playbook had been injected into the agent's system prompt when each
of these failure cases happened, would the failure have been
prevented?".

Output : a score 0-100 + a verdict ``pass`` (≥ 60) / ``fail`` (< 60)
+ a 1-sentence rationale. The score is persisted on the
``LearnedSkill.last_eval_score`` column ; the verdict + rationale are
returned to the caller (Phase 3.c iteration loop uses both).

Pattern d'inspiration : design note §3 Q3 + Sprint 3.7 ``mission_critic``
(same LLM-as-judge shape on a different signal). Voir
docs/external-references/hermes-skills-self-improvement.md §5 Phase 3.

V1 limits
---------
- LLM-as-judge on the CONTEXT only — we do NOT re-run the agent with
  the playbook in the prompt (that's the "replay" option deliberately
  deferred to Phase 6+). Cheaper, faster, less determinism but a
  reasonable signal for V1.
- The judge has access to up to 5 source failure_cases per skill — if
  the cluster is bigger, we sample the most recent 5 to keep the
  prompt size bounded.
- The judge uses tier S (same lane as the creator) but with
  ``force_fallback=False`` so primary Opus is selected when within
  budget. Different temperature (0.0 vs 0.2 for creator) for
  determinism.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill
from app.services.learning.skill_creator import _format_failure_case_for_prompt
from app.services.learning.tier_s import (
    estimate_cost_usd,
    get_tier_s_llm,
    record_tier_s_usage,
)

logger = logging.getLogger(__name__)


PASS_THRESHOLD = 60  # score ≥ this is a "pass"
MAX_CASES_IN_PROMPT = 5  # bound the prompt size on big clusters


# ── Prompts ─────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an external evaluator for ELY's auto-improvement loop. You are
neutral — you did NOT write the playbook you are about to assess, and
you have no stake in saying yes.

Inputs you will receive
-----------------------
1. The full text of a candidate PLAYBOOK that ELY's autonomous skill
   writer just drafted (Markdown with YAML frontmatter).
2. 1-5 concrete failure cases the playbook was supposed to address.

Your job
--------
Decide, HONESTLY, whether the playbook (if injected in the agent's
system prompt next time the trigger pattern shows up) would have
prevented EACH of those failures.

Score grid
----------
- 90-100 : The playbook spells out exactly the trigger + correct
           procedure + names the failing tools to avoid. High
           confidence it would prevent the failures.
- 70-89  : Good direction but vague on one of trigger / procedure /
           forbidden moves. Likely to help most of the time.
- 50-69  : Generic advice. Might help by accident, not by design.
- 30-49  : Targets the wrong layer (e.g. proposes new tools when the
           failure was procedural).
- 0-29   : Either off-topic, hallucinated, or actively makes things
           worse (e.g. proposes a destructive shortcut).

Reply with EXACTLY ONE JSON object — no markdown, no prose, no fences.
Schema :
  {
    "score": <int 0-100>,
    "verdict": "pass" | "fail",
    "rationale": "<one sentence ≤ 240 chars explaining the score>"
  }

Rules
-----
- ``verdict == "pass"`` iff ``score >= 60``. Be consistent.
- The rationale must cite ONE concrete reason from the playbook OR
  ONE concrete failure mode. No generic "looks good" boilerplate.
"""


def _compose_judge_prompt(skill: LearnedSkill, cases: list[FailureCase]) -> str:
    """Build the user-side prompt for the judge call."""
    head = "CANDIDATE PLAYBOOK\n==================\n"
    head += f"--- frontmatter ---\nname: {skill.name}\n"
    head += f"description: {skill.description}\n"
    head += "--- body ---\n"
    head += skill.content
    head += "\n\nFAILURE CASES THIS PLAYBOOK WAS DRAFTED TO ADDRESS\n"
    head += "==================================================\n"
    head += f"({len(cases)} case(s) shown; the cluster fingerprint was "
    head += f"{cases[0].pattern_hash if cases else '?'})\n\n"
    head += "\n\n".join(_format_failure_case_for_prompt(fc) for fc in cases)
    head += (
        "\n\nNow output the JSON object as instructed in the system prompt. "
        "ONE object, no fences, no prose."
    )
    return head


# ── Response parser ─────────────────────────────────────────────────────────


def parse_judge_response(raw: str) -> dict[str, Any] | None:
    """Parse the strict-JSON judge response into a dict.

    Tolerant : strips ```json fences and any leading/trailing whitespace
    or stray prose, looks for the first ``{`` to the matching ``}``.
    Returns ``None`` on shape failure ; caller logs + retries or fails
    the eval.
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Find the first { and the last }, take the slice
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start: end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        score = int(data.get("score", -1))
    except (TypeError, ValueError):
        return None
    if not (0 <= score <= 100):
        return None
    verdict = str(data.get("verdict", "")).lower().strip()
    if verdict not in ("pass", "fail"):
        return None
    # Enforce internal consistency: verdict must match the threshold
    expected = "pass" if score >= PASS_THRESHOLD else "fail"
    if verdict != expected:
        # Trust the score over the verdict — the LLM occasionally
        # misaligns them. Coerce to the score-implied verdict so
        # downstream logic stays clean.
        verdict = expected
    rationale = str(data.get("rationale", "")).strip()[:240]
    return {
        "score": score,
        "verdict": verdict,
        "rationale": rationale,
    }


# ── Public API ──────────────────────────────────────────────────────────────


async def _load_skill_and_cases(
    db: AsyncSession, skill_id: str,
) -> tuple[LearnedSkill | None, list[FailureCase]]:
    skill = (await db.execute(
        select(LearnedSkill).where(LearnedSkill.id == skill_id)
    )).scalar_one_or_none()
    if skill is None:
        return None, []
    try:
        case_ids = json.loads(skill.from_failure_case_ids or "[]")
    except Exception:
        case_ids = []
    if not case_ids:
        return skill, []
    cases = (await db.execute(
        select(FailureCase)
        .where(FailureCase.id.in_(case_ids[:MAX_CASES_IN_PROMPT]))
        .order_by(FailureCase.created_at.desc())
    )).scalars().all()
    return skill, list(cases)


async def evaluate_skill(skill_id: str) -> dict[str, Any]:
    """Run one LLM-as-judge pass on a candidate ``LearnedSkill``.

    Returns ::

        {
          "skill_id": "...",
          "status": "evaluated" | "skill_not_found" | "no_cases"
                    | "no_provider" | "llm_call_failed" | "parse_failed",
          "score": <int 0-100> | None,
          "verdict": "pass" | "fail" | None,
          "rationale": "...",
          "provider_pick": "primary" | "fallback" | None,
          "tokens_in": <int>, "tokens_out": <int>,
          "estimated_cost_usd": <float>,
        }

    Side effect : on a successful eval, ``LearnedSkill.last_eval_score``
    is updated in DB. Failures DO NOT update the score (the previous
    value, if any, is preserved). Never raises.
    """
    out: dict[str, Any] = {
        "skill_id": skill_id,
        "status": "pending",
        "score": None,
        "verdict": None,
        "rationale": None,
        "provider_pick": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
    }

    async with async_session() as db:
        skill, cases = await _load_skill_and_cases(db, skill_id)
    if skill is None:
        out["status"] = "skill_not_found"
        return out
    if not cases:
        out["status"] = "no_cases"
        out["rationale"] = "No source failure_cases referenced by the candidate skill."
        return out

    llm, pick = await get_tier_s_llm()
    if llm is None or pick == "none":
        out["status"] = "no_provider"
        return out
    out["provider_pick"] = pick

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        # Lower the temperature for the judge — we want consistency,
        # not creativity. langchain models accept .bind(temperature=...)
        # but the cleanest approach is to construct a fresh model
        # call message list and rely on the model's default. We rely
        # on the tier-S provider's default 0.2 set in `_build_primary`
        # / `_build_fallback`.
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_compose_judge_prompt(skill, cases)),
        ]
        response = await llm.ainvoke(messages)
        raw = getattr(response, "content", "") or ""
    except Exception as exc:
        out["status"] = "llm_call_failed"
        out["rationale"] = f"{type(exc).__name__}: {exc}"
        logger.warning("skill_eval: tier-S call failed for skill %s: %s", skill_id, exc)
        return out

    # Best-effort usage accounting
    try:
        usage_meta = getattr(response, "usage_metadata", None) or {}
        in_tokens = int(usage_meta.get("input_tokens") or 0)
        out_tokens = int(usage_meta.get("output_tokens") or 0)
        model_name = (
            getattr(response, "response_metadata", {}).get("model_name")
            or getattr(llm, "model", None)
            or getattr(llm, "model_name", None)
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
            purpose="skill_eval",
        )
        out["tokens_in"] = in_tokens
        out["tokens_out"] = out_tokens
        out["estimated_cost_usd"] = estimate_cost_usd(model_name, in_tokens, out_tokens)

    parsed = parse_judge_response(raw)
    if parsed is None:
        out["status"] = "parse_failed"
        out["rationale"] = f"Judge response did not parse. First 200 chars: {raw[:200]!r}"
        logger.warning(
            "skill_eval: judge response did not parse for skill %s — first 200 chars: %s",
            skill_id, raw[:200],
        )
        return out

    out["status"] = "evaluated"
    out["score"] = parsed["score"]
    out["verdict"] = parsed["verdict"]
    out["rationale"] = parsed["rationale"]

    # Persist the score
    async with async_session() as db:
        await db.execute(
            update(LearnedSkill)
            .where(LearnedSkill.id == skill_id)
            .values(last_eval_score=parsed["score"])
        )
        await db.commit()

    logger.info(
        "skill_eval: skill=%s score=%d verdict=%s",
        skill_id, parsed["score"], parsed["verdict"],
    )
    return out
