# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_creator.py
# @brief      Sprint 4b Phase 3.a — autonomous skill (playbook) generator
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill creator — Sprint 4b Phase 3.a.

Reads ``failure_cases`` that haven't been turned into a skill yet,
clusters them by ``pattern_hash``, and asks the tier-S LLM (Opus 4.5
primary, DeepSeek pro fallback) to write a Markdown playbook that
would have prevented each cluster's failure pattern.

Pattern d'inspiration : Hermes ``tools/skill_manager_tool.py`` (action
``create``, SKILL.md format) + the prompt rationale in
``agent/prompt_builder.py:177-183``. Voir
docs/external-references/hermes-skills-self-improvement.md §5 Phase 3.

Public entry point
------------------
``run_skill_creator_batch(user_id, batch_size)`` — picks at most
``batch_size`` clusters of unprocessed failure_cases for ``user_id``,
drafts one ``LearnedSkill`` (status ``candidate``) per cluster, marks
the underlying failure_cases as ``processed_at = now``, and returns a
summary dict for the admin endpoint.

V1 limits (consciously narrow, expanded in Phases 3.b–5)
---------------------------------------------------------
- Only generates Markdown playbooks (not Python tools — V2)
- Does NOT evaluate the playbook (that's Phase 3.b ``skill_eval``)
- Does NOT promote anything to ``active`` (Phase 4 — HITL admin)
- Does NOT inject playbooks into the system prompt (also Phase 4)
- Default LLM is Opus 4.5 via tier S; budget cap from Phase 2 applies

The whole module is best-effort: a generation failure on one cluster
must not abort the batch. We log + skip + move on.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning.tier_s import (
    estimate_cost_usd,
    get_tier_s_llm,
    record_tier_s_usage,
)

logger = logging.getLogger(__name__)


# ── Prompts ─────────────────────────────────────────────────────────────────

# We split the prompt into a system message (stable, prompt-cacheable for
# Anthropic) and a user message (per-cluster, dynamic). Opus respects this
# split and bills the system portion at ~10 % after the first call.

_SYSTEM_PROMPT = """\
You are ELY's autonomous skill writer. ELY is a sovereign AI agent built
on FastAPI + LangGraph that runs Gmail / Calendar / Drive / Notes /
Tasks / browser tools for self-hosted users.

You are given ONE failure pattern (1 or more concrete failure cases that
share the same fingerprint) where the live agent got something wrong
recently: HITL refused, hallucinated success, or low-quality mission
critique. Your job is to write a SHORT Markdown PLAYBOOK that, if injected
into the agent's system prompt next time this pattern shows up, would
prevent the failure from happening again.

A playbook is procedural memory, not a tool. It tells the agent
"WHEN you see X, DO Y in this order, NEVER do Z". It is NOT code.

Strict output contract
----------------------
Reply with EXACTLY a fenced markdown block starting with `---` (YAML
frontmatter) and finishing with a procedure section. NO other text
before or after the fenced block. Schema:

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

Quality bar
-----------
- Concrete and actionable: name the actual tools (gmail_trash_emails,
  drive_create_file, etc.), not vague verbs.
- Defensive: when in doubt, propose asking the user before acting.
- Tight: < 300 words total. Token economy matters.
- Cite the failure modes verbatim when useful (1 short quote max).
"""


def _format_failure_case_for_prompt(fc: FailureCase) -> str:
    """One compact paragraph per failure case for the user prompt."""
    payload = {}
    try:
        payload = json.loads(fc.replay_payload or "{}")
    except Exception:
        pass
    kind = payload.get("signal_kind", fc.signal_table)
    bits = [f"signal={kind}", f"tier_llm={fc.tier_llm or '?'}"]
    if "tool_name" in payload:
        bits.append(f"tool={payload['tool_name']}")
    if "decision" in payload:
        bits.append(f"decision={payload['decision']}")
    if "quality_score" in payload:
        bits.append(f"quality_score={payload['quality_score']}")
    if "honest_completion" in payload:
        bits.append(f"honest={payload['honest_completion']}")
    head = " | ".join(bits)

    extras: list[str] = []
    if payload.get("action_description"):
        extras.append(f"  Action that was refused: {payload['action_description']!r}")
    if payload.get("original_response"):
        extras.append(f"  Agent claimed: {payload['original_response']!r}")
    if payload.get("destructive_tools_invoked") is not None:
        dest = payload["destructive_tools_invoked"]
        dest_str = repr(dest) if dest else "(NONE — that is the failure)"
        extras.append(f"  Destructive tools actually called: {dest_str}")
    if payload.get("main_issue"):
        extras.append(f"  Critic main issue: {payload['main_issue']!r}")

    return f"- [case#{fc.id}] {head}\n" + "\n".join(extras)


def _compose_user_prompt(cluster: list[FailureCase]) -> str:
    """User message for one cluster of similar failures."""
    head = f"Failure pattern (cluster fingerprint = {cluster[0].pattern_hash})\n"
    head += f"Number of cases in this cluster: {len(cluster)}\n\n"
    head += "Cases:\n"
    body = "\n\n".join(_format_failure_case_for_prompt(fc) for fc in cluster)
    tail = (
        "\n\nWrite the playbook now. Remember: ONLY the fenced markdown block "
        "with YAML frontmatter, no other text."
    )
    return head + body + tail


# ── Output parser ───────────────────────────────────────────────────────────


def parse_playbook_response(raw: str) -> dict[str, Any] | None:
    """Parse the tier-S response into (frontmatter dict, body markdown).

    Tolerant: accepts the playbook with or without surrounding fences,
    with or without a leading prose paragraph (we strip up to the first
    ``---``). Returns None on shape failure — the caller logs + skips.
    """
    if not raw:
        return None
    text = raw.strip()

    # Strip ```markdown / ``` fences if present
    if text.startswith("```"):
        # take everything between the first and last fence
        first_nl = text.find("\n")
        if first_nl < 0:
            return None
        text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    if not text.startswith("---"):
        # Maybe the model wrapped it in prose — find the frontmatter start
        idx = text.find("\n---\n")
        if idx < 0:
            idx = text.find("---")
            if idx < 0:
                return None
            text = text[idx:]
        else:
            text = text[idx + 1:]

    # Split frontmatter from body
    after = text[3:]  # strip leading ---
    end = after.find("\n---")
    if end < 0:
        return None
    fm_block = after[:end].strip()
    body = after[end + 4:].lstrip("\n").strip()

    # Parse frontmatter — accept YAML via yaml lib OR fall back to k:v
    try:
        import yaml  # type: ignore
        fm = yaml.safe_load(fm_block) or {}
        if not isinstance(fm, dict):
            return None
    except ImportError:
        fm = {}
        for line in fm_block.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()

    name = str(fm.get("name", "")).strip()
    description = str(fm.get("description", "")).strip()
    if not name or not description:
        return None

    return {
        "name": name[:64],
        "description": description[:1024],
        "frontmatter": fm,
        "body": body,
    }


# ── Public API ──────────────────────────────────────────────────────────────


async def _fetch_unprocessed_cases(
    db: AsyncSession, user_id: str, batch_size: int,
) -> list[list[FailureCase]]:
    """Pick top N clusters of unprocessed failure_cases for the user.

    Sorting heuristic V1 : the cluster with the MOST recent activity
    first, then by case count. Cap at ``batch_size`` clusters.
    """
    result = await db.execute(
        select(FailureCase)
        .where(
            FailureCase.user_id == user_id,
            FailureCase.processed_at.is_(None),
            FailureCase.pattern_hash.is_not(None),
        )
        .order_by(FailureCase.created_at.desc())
        .limit(200)  # window — never more than 200 rows
    )
    rows = result.scalars().all()
    if not rows:
        return []

    # Group by pattern_hash, preserving insertion order
    clusters: dict[str, list[FailureCase]] = {}
    for fc in rows:
        clusters.setdefault(fc.pattern_hash, []).append(fc)

    # Sort clusters: by latest case timestamp desc, then by size desc
    sorted_clusters = sorted(
        clusters.values(),
        key=lambda c: (max(fc.created_at for fc in c), len(c)),
        reverse=True,
    )
    return sorted_clusters[:batch_size]


async def _draft_skill_for_cluster(
    cluster: list[FailureCase],
    user_id: str,
) -> tuple[LearnedSkill | None, dict[str, Any]]:
    """Ask tier-S to write a playbook for one cluster of cases.

    Returns ``(skill_row, info_dict)``. ``skill_row`` is the unflushed
    ``LearnedSkill`` object ready to ``db.add``; None on any failure.
    ``info_dict`` carries the picked provider, raw response (truncated),
    and a status string for the admin endpoint's response.
    """
    info: dict[str, Any] = {
        "cluster_size": len(cluster),
        "pattern_hash": cluster[0].pattern_hash,
        "case_ids": [fc.id for fc in cluster],
        "status": "pending",
    }

    llm, pick = await get_tier_s_llm()
    if llm is None or pick == "none":
        info["status"] = "no_provider"
        info["error"] = "No tier-S provider configured (Anthropic + DeepSeek both absent)."
        return None, info
    info["provider_pick"] = pick

    # Call the LLM
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        user_prompt = _compose_user_prompt(cluster)
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = await llm.ainvoke(messages)
        raw = getattr(response, "content", "") or ""
    except Exception as exc:
        info["status"] = "llm_call_failed"
        info["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "skill_creator: tier-S call failed (%s): %s",
            info["pattern_hash"], exc,
        )
        return None, info

    # Best-effort usage accounting — read .usage_metadata when present
    in_tokens = out_tokens = 0
    model_name = ""
    try:
        usage_meta = getattr(response, "usage_metadata", None) or {}
        in_tokens = int(usage_meta.get("input_tokens") or 0)
        out_tokens = int(usage_meta.get("output_tokens") or 0)
        model_name = getattr(response, "response_metadata", {}).get("model_name") or ""
        if not model_name:
            model_name = (
                getattr(llm, "model", None)
                or getattr(llm, "model_name", None)
                or "tier-s"
            )
    except Exception:
        pass

    if in_tokens or out_tokens:
        await record_tier_s_usage(
            user_id=user_id,
            model=model_name,
            provider="anthropic" if pick == "primary" else "deepseek",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            purpose="skill_creator",
        )
        info["tokens_in"] = in_tokens
        info["tokens_out"] = out_tokens
        info["estimated_cost_usd"] = estimate_cost_usd(model_name, in_tokens, out_tokens)

    # Parse response
    parsed = parse_playbook_response(raw)
    if parsed is None:
        info["status"] = "parse_failed"
        info["raw_excerpt"] = raw[:300]
        logger.warning(
            "skill_creator: tier-S response did not parse — pattern_hash=%s "
            "first 200 chars: %s",
            info["pattern_hash"], raw[:200],
        )
        return None, info

    # Build the LearnedSkill row (NOT committed here — caller commits)
    skill = LearnedSkill(
        user_id=user_id,
        name=parsed["name"],
        description=parsed["description"],
        content=parsed["body"],
        frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
        status=SkillStatus.CANDIDATE,
        source=SkillSource.AUTO_GENERATED,
        iteration_count=1,
        from_failure_case_ids=json.dumps(
            info["case_ids"], ensure_ascii=False,
        ),
        rationale=(
            f"Auto-generated by skill_creator from {len(cluster)} failure cases "
            f"(pattern {info['pattern_hash']}). Cases: {info['case_ids']}."
        ),
    )
    info["status"] = "drafted"
    info["skill_name"] = parsed["name"]
    return skill, info


async def run_skill_creator_batch(
    *,
    user_id: str,
    batch_size: int = 3,
) -> dict[str, Any]:
    """Run one batch of skill generation for ``user_id``.

    Returns ::

        {
          "user_id": "...",
          "batch_size": 3,
          "clusters_processed": 2,
          "drafts": [
            {"status": "drafted", "skill_name": "...", ...},
            {"status": "parse_failed", "raw_excerpt": "...", ...},
          ],
          "skills_created": 1,
        }

    Best-effort: a per-cluster failure logs + moves on, never aborts the
    batch. Empty input → empty result with zero counts.
    """
    if not user_id:
        return {"error": "user_id is required", "skills_created": 0, "drafts": []}
    batch_size = max(1, min(int(batch_size or 1), 10))

    summary: dict[str, Any] = {
        "user_id": user_id,
        "batch_size": batch_size,
        "clusters_processed": 0,
        "drafts": [],
        "skills_created": 0,
    }

    async with async_session() as db:
        clusters = await _fetch_unprocessed_cases(db, user_id, batch_size)

    if not clusters:
        return summary

    now = datetime.now(timezone.utc)
    for cluster in clusters:
        summary["clusters_processed"] += 1
        skill, info = await _draft_skill_for_cluster(cluster, user_id)
        summary["drafts"].append(info)
        if skill is None:
            continue

        # Persist the skill + mark its source failure_cases processed
        async with async_session() as db:
            db.add(skill)
            await db.flush()  # populate skill.id
            await db.execute(
                update(FailureCase)
                .where(FailureCase.id.in_(info["case_ids"]))
                .values(processed_at=now, learned_skill_id=skill.id)
            )
            await db.commit()
            summary["skills_created"] += 1
            info["learned_skill_id"] = skill.id
            logger.info(
                "skill_creator: created candidate skill %s (%s) from %d cases",
                skill.id, skill.name, len(info["case_ids"]),
            )

    return summary
