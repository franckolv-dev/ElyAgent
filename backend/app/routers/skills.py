# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/skills.py
# @brief      REST API for the skill registry and per-user skill preferences
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""REST API for the skill registry and per-user skill preferences.

Endpoints
---------
GET  /skills/              List all skills with enabled status for the current user
PUT  /skills/{skill_name}  Enable/disable a skill (or save its config)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.skill_preference import SkillPreference
from app.skills import get_skill_registry

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Schemas                                                              #
# ------------------------------------------------------------------ #

class SkillUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None


# ------------------------------------------------------------------ #
# Routes                                                               #
# ------------------------------------------------------------------ #

@router.get("/")
async def list_skills(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all registered skills with their enabled status for the caller."""
    result = await db.execute(
        select(SkillPreference).where(SkillPreference.user_id == current_user.id)
    )
    prefs: dict[str, SkillPreference] = {
        p.skill_name: p for p in result.scalars().all()
    }

    registry = get_skill_registry()
    return [
        {
            "name": s.name,
            "display_name": s.display_name,
            "description": s.description,
            "icon": s.icon,
            "version": s.version,
            "author": s.author,
            "scopes": s.scopes,
            "enabled_by_default": s.enabled_by_default,
            "enabled": prefs[s.name].enabled if s.name in prefs else s.enabled_by_default,
            "tool_count": len(s.tools),
            "tool_names": [t.name for t in s.tools],
            "config": (
                json.loads(prefs[s.name].config_json)
                if s.name in prefs and prefs[s.name].config_json
                else {}
            ),
        }
        for s in registry.list_skills()
    ]


@router.put("/{skill_name}")
async def update_skill(
    skill_name: str,
    body: SkillUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable, disable or configure a skill for the current user."""
    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    result = await db.execute(
        select(SkillPreference).where(
            SkillPreference.user_id == current_user.id,
            SkillPreference.skill_name == skill_name,
        )
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = SkillPreference(
            user_id=current_user.id,
            skill_name=skill_name,
            enabled=skill.enabled_by_default,
        )
        db.add(pref)

    if body.enabled is not None:
        pref.enabled = body.enabled
    if body.config is not None:
        pref.config_json = json.dumps(body.config)

    await db.commit()
    await db.refresh(pref)

    logger.info(
        "Skill '%s' %s for user %s",
        skill_name,
        "enabled" if pref.enabled else "disabled",
        current_user.id,
    )
    return {
        "name": skill_name,
        "enabled": pref.enabled,
        "config": json.loads(pref.config_json) if pref.config_json else {},
    }
