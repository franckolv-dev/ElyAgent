"""SkillRegistry — central catalogue of all available skills.

Responsibilities
----------------
- Maintain an ordered dict of registered Skill objects.
- Expose ``all_tools`` (flat list of every tool from every skill) so that
  ``nodes.py`` can build the LLM binding in one call.
- Expose ``get_user_active_tools()`` for per-user filtering based on the
  ``skill_preferences`` DB table.
- Expose ``list_skills()`` for the REST API.

Singleton
---------
Use ``get_skill_registry()`` everywhere.  The registry is empty at import
time; skills are registered by importing ``app.skills.builtin`` (which runs
module-level ``get_skill_registry().register(...)`` side-effects).
``app.main`` imports ``app.skills.builtin`` at startup, so by the time any
request is served the registry is fully populated.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.skills.base import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self) -> None:
        # Insertion-ordered dict: skills appear in registration order
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, skill: Skill) -> None:
        """Add a skill to the registry.  Safe to call multiple times
        (idempotent — second registration for the same name is ignored)."""
        if skill.name in self._skills:
            return
        self._skills[skill.name] = skill
        logger.debug("Skill registered: %s (%d tools)", skill.name, len(skill.tools))

    # ------------------------------------------------------------------ #
    # Query helpers                                                        #
    # ------------------------------------------------------------------ #

    @property
    def all_tools(self) -> list:
        """Flat list of every tool from every registered skill."""
        tools: list = []
        for skill in self._skills.values():
            tools.extend(skill.tools)
        return tools

    def list_skills(self) -> list[Skill]:
        """All registered skills in registration order."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    # ------------------------------------------------------------------ #
    # Per-user active tools                                               #
    # ------------------------------------------------------------------ #

    async def get_user_active_tools(self, user_id: str, db) -> list:
        """Return tools for skills that are currently enabled for *user_id*.

        Falls back to ``Skill.enabled_by_default`` when no preference row
        exists for a given skill.
        """
        from app.models.skill_preference import SkillPreference
        from sqlalchemy import select

        result = await db.execute(
            select(SkillPreference).where(SkillPreference.user_id == user_id)
        )
        prefs: dict[str, bool] = {
            p.skill_name: p.enabled for p in result.scalars().all()
        }

        tools: list = []
        for name, skill in self._skills.items():
            if prefs.get(name, skill.enabled_by_default):
                tools.extend(skill.tools)
        return tools

    def skills_summary(self) -> str:
        """One-line-per-skill text for injection into the system prompt."""
        lines = []
        for s in self._skills.values():
            names = ", ".join(t.name for t in s.tools)
            lines.append(f"{s.icon} {s.display_name} : {s.description} [{names}]")
        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry()
