# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/active_skills.py
# @brief      Sprint 4b Phase 4.b — read + format active LearnedSkills for the agent prompt
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Active skills query + prompt formatter — Sprint 4b Phase 4.b.

Once an admin has promoted a `candidate` LearnedSkill to `active`
(Phase 4.a), it becomes part of the agent's procedural memory: its
short description gets injected into the system prompt every turn
(via memory_snapshot), and the agent can pull its full content on
demand via the new `skill_view` tool.

Progressive disclosure (Hermes pattern)
---------------------------------------
- Tier 1 (always in prompt) : the `description` field (≤200 chars).
  ~50 tokens per skill, capped at MAX_SKILLS_IN_PROMPT = 20.
- Tier 2 (on demand) : the full `content` body, fetched by the agent
  via `skill_view(name)`. Bumps `use_count` + `last_used_at` so the
  Phase-5 curator can detect stale skills.

The block is added to the existing `<user_state>` + memory_block in
`memory_snapshot.build_memory_snapshot`. Best-effort: any DB hiccup
returns an empty block (the agent runs without procedural memory
just fine — that's the pre-Phase-4 baseline).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.learned_skill import LearnedSkill, SkillStatus

logger = logging.getLogger(__name__)


# Cap on number of active skills injected per turn. 20 skills ×
# ~50 tokens each = ~1k tokens, an acceptable fraction of the
# ~23k system prompt budget. Tune via `LEARNED_SKILLS_PROMPT_MAX` env.
MAX_SKILLS_IN_PROMPT = 20


async def get_active_skills_for_user(
    user_id: str,
    limit: int = MAX_SKILLS_IN_PROMPT,
) -> list[LearnedSkill]:
    """Return up to ``limit`` active LearnedSkills for ``user_id``.

    Ordered by `use_count desc, last_used_at desc, created_at desc`
    so the most useful skills are surfaced first — when we cap at
    `limit`, we lose the long-tail least-used skills first.

    Best-effort: a DB outage returns an empty list, the caller will
    just inject an empty block.
    """
    if not user_id:
        return []
    try:
        async with async_session() as db:
            result = await db.execute(
                select(LearnedSkill)
                .where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
                .order_by(
                    LearnedSkill.use_count.desc(),
                    LearnedSkill.last_used_at.desc().nulls_last(),
                    LearnedSkill.created_at.desc(),
                )
                .limit(limit)
            )
            return list(result.scalars().all())
    except Exception as exc:
        logger.debug("get_active_skills_for_user failed (%s) — returning []", exc)
        return []


def format_active_skills_block(skills: list[LearnedSkill]) -> str:
    """Render the active-skills section for the system prompt.

    Returns the empty string when there are no skills — the caller
    safely concatenates without polluting the prompt for first-time
    users.

    Format :
        <learned_skills>
        Tu as N playbook(s) appris(es) (voir le contenu complet via
        skill_view) :
          - name-1 : description
          - name-2 : description
        </learned_skills>
    """
    if not skills:
        return ""
    n = len(skills)
    lines = [
        "<learned_skills>",
        (
            f"Tu as {n} playbook{'s' if n > 1 else ''} appris{'es' if n > 1 else 'e'} "
            "(procédures éprouvées). AVANT d'exécuter une tâche qui correspond "
            "à l'un d'eux, lis-le EN ENTIER via le tool `skill_view` et suis sa "
            "procédure — ne l'improvise pas. Liste :"
        ),
    ]
    for s in skills:
        # Trim description to a single line in case the writer slipped
        # a newline through.
        desc = (s.description or "").replace("\n", " ").strip()
        if len(desc) > 200:
            desc = desc[:197] + "…"
        lines.append(f"  - {s.name} : {desc}")
    lines.append("</learned_skills>")
    return "\n".join(lines) + "\n"


async def bump_skill_usage(skill_id: str) -> bool:
    """Increment `use_count` and set `last_used_at = now` for one skill.

    Called by the `skill_view` tool right after a successful fetch.
    Best-effort: a write failure logs at DEBUG and returns False.
    The agent still gets the content — only the analytics suffer.
    """
    if not skill_id:
        return False
    try:
        async with async_session() as db:
            result = await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id == skill_id)
                .values(
                    use_count=LearnedSkill.use_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            return result.rowcount > 0
    except Exception as exc:
        logger.debug("bump_skill_usage(%s) failed (swallowed): %s", skill_id, exc)
        return False


async def get_active_skill_by_name(
    user_id: str,
    name: str,
) -> LearnedSkill | None:
    """Fetch one active LearnedSkill by (user_id, name). Used by the
    `skill_view` tool. Returns None on not-found OR on DB outage."""
    if not user_id or not name:
        return None
    try:
        async with async_session() as db:
            return (await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.name == name,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
            )).scalar_one_or_none()
    except Exception as exc:
        logger.debug("get_active_skill_by_name(%s, %s) failed: %s", user_id[:8] if user_id else "?", name, exc)
        return None
