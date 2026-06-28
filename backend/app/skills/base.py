# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/base.py
# @brief      Skill — the unit of capability in the ELY plugin system
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
"""Skill — the unit of capability in the ELY plugin system.

A Skill groups a set of related LangChain tools under a common identity
with metadata (name, description, icon, required scopes).

Usage (defining a new skill)
------------------------------
    from app.skills.base import Skill, Domain
    from app.skills.registry import get_skill_registry

    my_skill = Skill(
        name="my_service",
        display_name="My Service",
        description="Does useful things with My Service",
        icon="🔧",
        scopes=["my_service_api_key"],   # optional config keys
        domains=[Domain.WORKSPACE],      # specialist domain(s) this skill belongs to
        tools=[my_tool_a, my_tool_b],
    )
    get_skill_registry().register(my_skill)

The ``name`` field is the stable identifier stored in the database for
per-user skill preferences.  Change it only with a DB migration.

The ``domains`` field is the SOURCE OF TRUTH for which specialist agents
have access to this skill's tools. The supervisor and sub-agent factory
derive their per-domain tool sets from this list — adding a new tool no
longer requires editing supervisor.py or sub_agents/config.py.

Use ``Domain.UNIVERSAL`` to mark a skill that is injected into EVERY
specialist domain (e.g. memory/preferences/RAG tools).
"""
from __future__ import annotations

from dataclasses import dataclass, field


class Domain:
    """Specialist domain identifiers (kept as plain strings to stay
    compatible with ``supervisor.Domain = Literal[...]``).

    These are not strings inside a Python ``Enum`` on purpose — many
    callsites compare against the ``Literal`` defined in ``supervisor``
    and serialize values as plain ``str`` for routing/state.
    """

    RESEARCH = "research"
    WORKSPACE = "workspace"
    INFRA = "infra"
    CREATIVE = "creative"
    DATA = "data"
    MEMORY = "memory"
    DESKTOP = "desktop"
    GENERAL = "general"
    SYSTEM = "system"
    DIAG = "diag"
    # Sentinel — skill is injected into EVERY specialist domain
    # (used by memory/preferences/RAG tools that must always be available).
    UNIVERSAL = "_universal"


@dataclass
class Skill:
    # Required fields
    name: str           # stable unique slug  e.g. "google_gmail"
    display_name: str   # human-readable name e.g. "Gmail"
    description: str    # one-liner shown in the settings UI
    icon: str           # emoji shown next to the display name
    tools: list         # list of LangChain @tool callables

    # Optional metadata
    version: str = "1.0.0"
    author: str = "built-in"
    # Logical permission scopes — "google_oauth", "ssh", "internet", …
    scopes: list[str] = field(default_factory=list)
    # Whether the skill is on for new users before they change anything
    enabled_by_default: bool = True
    # Specialist domain(s) this skill belongs to. Source of truth for the
    # per-domain tool sets used by ``supervisor.py`` and
    # ``sub_agents/config.py``. Defaults to ``[]`` for backward compat — but
    # every builtin skill SHOULD declare its domains explicitly so the
    # mission planner / specialist routing can see it.
    domains: list[str] = field(default_factory=list)
