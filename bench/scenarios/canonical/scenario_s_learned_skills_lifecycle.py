# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_s_learned_skills_lifecycle.py
# @brief      Sprint 3.7.3 J4 — structural regression : Sprint 4b Phase 5.b
#             user surface. list / pin / forget round-trip on a learned
#             skill, plus the cross-user 404 (not 403) isolation contract.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario S — learned-skills list/pin/forget lifecycle."""
from __future__ import annotations


NAME = "S — learned-skills list/pin/forget lifecycle"
DESCRIPTION = (
    "Phase 5.b round-trip : pin toggles `pinned`, forget moves status → "
    "archived (re-forget is a no-op), list surfaces the skill, and a foreign "
    "user gets 404 (not 403) so the skill's existence isn't leaked."
)
TAGS = ["shallow"]


async def run() -> dict:
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.database import async_session
    from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
    from app.models.user import User
    from app.routers.me_learning_skills import (
        PinRequest,
        forget_skill,
        list_my_skills,
        pin_skill,
    )
    from bench.scenarios._base import from_checks, throwaway_user

    async def _seed(uid: str) -> str:
        async with async_session() as db:
            s = LearnedSkill(
                user_id=uid,
                name="archive-before-claiming",
                description="Vérifier avant d'archiver",
                content="# Body\n## Procedure\n1. step",
                frontmatter_json="{}",
                status=SkillStatus.ACTIVE,
                source=SkillSource.AUTO_GENERATED,
                iteration_count=1,
                from_failure_case_ids="[]",
                use_count=0,
            )
            db.add(s)
            await db.commit()
            await db.refresh(s)
            return s.id

    async with throwaway_user("bench_skill_lc") as uid:
        skill_id = await _seed(uid)

        async with async_session() as db:
            user = await db.get(User, uid)
            pinned = await pin_skill(skill_id, PinRequest(pinned=True), user=user, db=db)
            forgotten = await forget_skill(skill_id, user=user, db=db)
            reforgotten = await forget_skill(skill_id, user=user, db=db)  # no-op
            listing = await list_my_skills(user=user, db=db)

        # Cross-user isolation : a foreign owner must get a 404.
        cross_user_404 = False
        async with throwaway_user("bench_skill_foreign") as fuid:
            async with async_session() as db:
                fuser = await db.get(User, fuid)
                try:
                    await pin_skill(
                        skill_id, PinRequest(pinned=True), user=fuser, db=db
                    )
                except HTTPException as exc:
                    cross_user_404 = exc.status_code == 404

        checks = {
            "pin_sets_pinned": pinned.pinned is True,
            "forget_archives": forgotten.status == SkillStatus.ARCHIVED,
            "reforget_is_noop": reforgotten.status == SkillStatus.ARCHIVED,
            "list_includes_skill": any(s.id == skill_id for s in listing),
            "cross_user_404_not_403": cross_user_404,
        }
        return from_checks(checks, skill_id=skill_id, listed=len(listing))
