# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/registry.py
# @brief      SkillRegistry — central catalogue of all available skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
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

from app.skills.base import Skill, Domain

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self) -> None:
        # Insertion-ordered dict: skills appear in registration order
        self._skills: dict[str, Skill] = {}
        # Incremented on every register/unregister — used to detect hot-reload
        self._version: int = 0

    @property
    def tools_version(self) -> int:
        return self._version

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, skill: Skill) -> None:
        """Add a skill to the registry.  Safe to call multiple times
        (idempotent — second registration for the same name is ignored)."""
        if skill.name in self._skills:
            return
        self._skills[skill.name] = skill
        self._version += 1
        logger.debug("Skill registered: %s (%d tools)", skill.name, len(skill.tools))

    def register_or_replace(self, skill: Skill) -> None:
        """Register a skill, replacing any existing skill with the same name.

        Used by MCPClientManager to hot-reload MCP skills at runtime.
        """
        self._skills[skill.name] = skill
        self._version += 1
        logger.info("Skill registered/replaced: %s (%d tools)", skill.name, len(skill.tools))

    def unregister(self, skill_name: str) -> None:
        """Remove a skill from the registry (used by MCPClientManager)."""
        if skill_name in self._skills:
            del self._skills[skill_name]
            self._version += 1
            logger.info("Skill unregistered: %s", skill_name)

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

    # ------------------------------------------------------------------ #
    # Domain-driven helpers (Sprint 2 — eliminates the triple-registration trap) #
    # ------------------------------------------------------------------ #

    def _skills_for_domain(self, domain: str) -> list[Skill]:
        """Return all skills whose ``domains`` list includes *domain* OR
        ``Domain.UNIVERSAL`` (the latter are always-on across every domain)."""
        result: list[Skill] = []
        for skill in self._skills.values():
            if Domain.UNIVERSAL in skill.domains or domain in skill.domains:
                result.append(skill)
        return result

    def tools_by_domain(self, domain: str) -> list:
        """Return all LangChain tools whose parent skill includes *domain*.

        Used by ``supervisor.create_specialist_node`` and
        ``sub_agents.factory`` to filter the global tool list down to the
        subset relevant for a given specialist agent.
        """
        tools: list = []
        for skill in self._skills_for_domain(domain):
            tools.extend(skill.tools)
        return tools

    def tool_names_by_domain(self, domain: str) -> set[str]:
        """Set of tool ``.name`` for every tool of every skill in *domain*."""
        return {t.name for t in self.tools_by_domain(domain)}

    def all_tool_names(self) -> set[str]:
        """Set of every tool name registered, across all skills."""
        return {t.name for t in self.all_tools}

    def tools_catalog(self, per_domain: bool = True) -> str:
        """Return a formatted catalog of every tool, suitable for injection
        into a planner / supervisor prompt.

        Format (one line per tool) :
            ``- tool_name : first sentence of the tool description``

        When ``per_domain=True`` the catalog is grouped by domain header
        (``## research``, ``## workspace`` …). Universal tools appear under
        ``## universal``.

        Output is capped to ~150 lines worth of content — descriptions are
        truncated to their first sentence (or 120 chars max) to keep the
        prompt tight.
        """
        def _first_sentence(text: str | None) -> str:
            if not text:
                return ""
            text = " ".join(text.split())  # collapse whitespace
            # First sentence = up to first '.', '!', '?', or 120 chars
            for sep in (". ", "! ", "? ", ".\n"):
                idx = text.find(sep)
                if 0 < idx < 120:
                    return text[:idx].strip()
            return (text[:117] + "…") if len(text) > 120 else text

        def _tool_line(tool) -> str:
            desc = getattr(tool, "description", "") or ""
            return f"- {tool.name} : {_first_sentence(desc)}"

        if not per_domain:
            seen: set[str] = set()
            lines: list[str] = []
            for tool in self.all_tools:
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                lines.append(_tool_line(tool))
            return "\n".join(lines)

        # Grouped by domain — order matches Domain class declaration
        ordered_domains = [
            Domain.UNIVERSAL,
            Domain.RESEARCH,
            Domain.WORKSPACE,
            Domain.INFRA,
            Domain.CREATIVE,
            Domain.DATA,
            Domain.MEMORY,
            Domain.DESKTOP,
            Domain.SYSTEM,
            Domain.DIAG,
        ]
        seen: set[str] = set()
        chunks: list[str] = []
        for d in ordered_domains:
            if d == Domain.UNIVERSAL:
                skills = [s for s in self._skills.values() if Domain.UNIVERSAL in s.domains]
                header_label = "universal (toujours disponible)"
            else:
                skills = [s for s in self._skills.values()
                          if d in s.domains and Domain.UNIVERSAL not in s.domains]
                header_label = d
            if not skills:
                continue
            block_lines: list[str] = [f"## {header_label}"]
            for skill in skills:
                for tool in skill.tools:
                    if tool.name in seen:
                        continue
                    seen.add(tool.name)
                    block_lines.append(_tool_line(tool))
            chunks.append("\n".join(block_lines))

        # Catch any tool whose skill has no declared domain — append under
        # an "## (no-domain)" header so they're still visible to the planner
        # but the gap is obvious.
        orphans: list[str] = []
        for skill in self._skills.values():
            if skill.domains:
                continue
            for tool in skill.tools:
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                orphans.append(_tool_line(tool))
        if orphans:
            chunks.append("## (skills sans domaine déclaré)\n" + "\n".join(orphans))

        return "\n\n".join(chunks)


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry()
