# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_promotion.py
# @brief      Jalon 1 (portage Hermes) — auto-promotion candidate→active
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Auto-promotion of candidate playbooks to active — Jalon 1 (portage Hermes).

Hermes writes a reviewed skill straight to the active set after its
post-conversation review fork passes; there is **no human gate**. Ely keeps
the admin review UI as an *a posteriori* rejection filter, but the autonomous
loop promotes a candidate to ``active`` the moment ``skill_eval`` returns a
pass — otherwise the loop only ever produces candidates nobody clicks (the
funnel-dead pathology measured in the 2026-06-15 audit : 4 playbooks,
``use_count ≈ 0``).

Strict invariants:
  - Only ``markdown_playbook`` candidates are auto-promoted. ``python_tool``
    skills stay gated behind the (frozen) codegen funnel + HITL admin — the
    autonomous loop never auto-activates executable code.
  - Only ``candidate`` → ``active`` (idempotent when already active).
  - Never raises. A failure leaves the candidate untouched for the admin UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillStatus,
)

logger = logging.getLogger(__name__)


async def promote_candidate_to_active(skill_id: str, *, reason: str = "") -> bool:
    """Promote a passing ``candidate`` markdown playbook to ``active``.

    Returns True iff the skill is active after the call (including the
    idempotent already-active case). Best-effort: swallows + logs errors.
    """
    if not skill_id:
        return False
    try:
        async with async_session() as db:
            skill = (await db.execute(
                select(LearnedSkill).where(LearnedSkill.id == skill_id)
            )).scalar_one_or_none()
            if skill is None:
                return False
            if skill.status == SkillStatus.ACTIVE:
                return True  # idempotent
            if skill.content_format != SkillContentFormat.MARKDOWN_PLAYBOOK:
                # Funnel B (python_tool) stays gated behind HITL admin.
                logger.debug(
                    "promote_candidate_to_active: skip non-markdown %s (%s)",
                    skill_id, skill.content_format,
                )
                return False
            if skill.status != SkillStatus.CANDIDATE:
                logger.debug(
                    "promote_candidate_to_active: %s not a candidate (%s)",
                    skill_id, skill.status,
                )
                return False
            skill.status = SkillStatus.ACTIVE
            skill.updated_at = datetime.now(timezone.utc)
            # C4-3 — start the injection grace window (a fresh promotion
            # has use_count=0 and must not be cut by the top-N sort).
            skill.promoted_at = skill.updated_at
            await db.commit()
            logger.info(
                "skill_auto_promoted: id=%s name=%s reason=%s",
                skill.id, skill.name, (reason or "eval_pass")[:80],
            )
            return True
    except Exception as exc:
        logger.warning("promote_candidate_to_active(%s) failed: %s", skill_id, exc)
        return False
