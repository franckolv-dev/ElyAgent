# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/base.py
# @brief      Skill — the unit of capability in the ELY plugin system
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
"""Skill — the unit of capability in the ELY plugin system.

A Skill groups a set of related LangChain tools under a common identity
with metadata (name, description, icon, required scopes).

Usage (defining a new skill)
------------------------------
    from app.skills.base import Skill
    from app.skills.registry import get_skill_registry

    my_skill = Skill(
        name="my_service",
        display_name="My Service",
        description="Does useful things with My Service",
        icon="🔧",
        scopes=["my_service_api_key"],   # optional config keys
        tools=[my_tool_a, my_tool_b],
    )
    get_skill_registry().register(my_skill)

The ``name`` field is the stable identifier stored in the database for
per-user skill preferences.  Change it only with a DB migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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
