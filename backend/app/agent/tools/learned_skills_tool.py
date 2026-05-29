# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/learned_skills_tool.py
# @brief      Sprint 4b Phase 4.b — skill_view tool (progressive disclosure)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""`skill_view` tool — agent-side reader for the auto-learned playbooks.

The system prompt (via `memory_snapshot.build_memory_snapshot`) lists
every active LearnedSkill for the user as `name : description`
(progressive disclosure tier 1, ~50 tokens per skill). When the
agent decides a playbook is relevant to the current turn, it calls
`skill_view(name)` to load the full body (tier 2).

Calling the tool bumps `use_count` + `last_used_at` so the Phase 5
curator can detect stale skills (unused too long → archive).

Pattern d'inspiration : Hermes `tools/skills_tool.py` (the
`skill_view` flow + progressive disclosure idea), see
docs/external-references/hermes-skills-self-improvement.md §1.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


@register(
    domain=Domain.UNIVERSAL,
    skill_name="learned_skills",
    skill_display_name="Compétences auto-apprises",
    skill_description=(
        "Lecture des playbooks que ELY a écrit pour elle-même à partir de "
        "ses propres échecs (HITL refusé, hallucinations, missions critiquées). "
        "Le system prompt liste les playbooks actifs avec leur description ; "
        "ce tool retourne le contenu complet d'un playbook par son name."
    ),
    skill_icon="📘",
    enabled_by_default=True,
    skill_version="0.1.0",
)
@tool
async def skill_view(
    name: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Load the full content of an active learned playbook.

    USE THIS TOOL when the user's request matches the `description` of
    a playbook listed in the `<learned_skills>` block of your system
    prompt. The block shows you the playbook NAMES + their one-liner
    descriptions ; this tool returns the full Markdown body (with the
    "When this applies / Procedure / What NOT to do" sections) that
    you should follow before acting.

    Parameters
    ----------
    name : str
        The exact skill name as shown in `<learned_skills>` (a
        kebab-case slug like ``verify-destructive-action-before-claiming-success``).

    Returns
    -------
    The full Markdown body of the playbook, or an explicit
    "not found" message — never invent a response, the playbook either
    exists in DB for this user or it doesn't.
    """
    if not user_id:
        # Shouldn't happen — USER_ID_TOOLS injection guards this — but
        # defensive in case the wire-up regressing.
        return (
            "Internal error: skill_view called without an injected user_id. "
            "Refusing to fetch a learned skill across users."
        )
    name = (name or "").strip()
    if not name:
        return "Usage: skill_view(name='kebab-case-skill-name')."

    from app.services.learning.active_skills import (
        bump_skill_usage,
        get_active_skill_by_name,
    )

    skill = await get_active_skill_by_name(user_id, name)
    if skill is None:
        return (
            f"No active playbook named {name!r} is registered for you. "
            "Check the `<learned_skills>` block in your prompt for the "
            "exact names available, or proceed without this playbook."
        )

    # Best-effort usage tracking — failures never block the read.
    await bump_skill_usage(skill.id)

    # Reconstruct a minimal SKILL.md envelope so the agent has the full
    # context (description + body). Frontmatter is left implicit (the
    # body usually starts with a `# Title` heading anyway).
    return (
        f"# Playbook : {skill.name}\n"
        f"_{skill.description}_\n\n"
        f"{skill.content}"
    )
