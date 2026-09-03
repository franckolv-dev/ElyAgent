# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_r_skill_view_progressive_disclosure.py
# @brief      Sprint 3.7.3 J3 — canonical scenario R : Sprint 4b skill_view
#             progressive disclosure. The tool returns an active playbook's
#             full body (tier 2), bumps usage, returns a clear not-found for
#             unknown names, and never leaks another user's skill.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario R — skill_view progressive disclosure + isolation."""
from __future__ import annotations

import uuid


NAME = "R — skill_view progressive disclosure"
DESCRIPTION = (
    "skill_view returns an active LearnedSkill's full Markdown body (tier 2) "
    "+ bumps use_count ; an unknown name returns a clear not-found ; a "
    "foreign user_id never surfaces the skill (cross-user isolation)."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.agent.tools.learned_skills_tool import skill_view
    from app.database import async_session
    from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
    from bench.scenarios._base import from_checks, throwaway_user

    name = "verify-destructive-action-before-claiming-success"
    description = "Toujours vérifier qu'une action destructive a réussi avant de l'annoncer"
    content = (
        "# Vérifier avant d'annoncer\n"
        "## When this applies\nÀ chaque action destructive.\n"
        "## Procedure\n1. Appeler le tool.\n2. Lire le résultat.\n"
        "## What NOT to do\nNe jamais prétendre un succès non confirmé.\n"
    )

    async with throwaway_user("bench_skill") as uid:
        async with async_session() as db:
            db.add(LearnedSkill(
                user_id=uid,
                name=name,
                description=description,
                content=content,
                frontmatter_json="{}",
                status=SkillStatus.ACTIVE,
                source=SkillSource.AUTO_GENERATED,
                iteration_count=1,
                from_failure_case_ids="[]",
                use_count=0,
            ))
            await db.commit()

        # Tier-2 disclosure : full body for the owning user.
        body = await skill_view.ainvoke({"name": name, "user_id": uid})

        # Unknown name → clear not-found, never invented.
        missing = await skill_view.ainvoke(
            {"name": "ghost-playbook-xyz", "user_id": uid}
        )

        # Foreign user must NOT see this skill (isolation).
        foreign_uid = f"bench_foreign_{uuid.uuid4().hex[:8]}"
        foreign = await skill_view.ainvoke({"name": name, "user_id": foreign_uid})

        # use_count bumped by the successful view.
        async with async_session() as db:
            skill = (await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.user_id == uid, LearnedSkill.name == name
                )
            )).scalar_one_or_none()

        checks = {
            "body_has_name": name in body,
            "body_has_description": "vérifier" in body.lower(),
            "body_has_procedure": "## Procedure" in body,
            "unknown_name_not_found": "No active playbook" in missing,
            "foreign_user_isolated": "No active playbook" in foreign,
            "use_count_bumped": skill is not None and skill.use_count >= 1,
        }
        return from_checks(checks, use_count=getattr(skill, "use_count", None))
