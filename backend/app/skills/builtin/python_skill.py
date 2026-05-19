# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/python_skill.py
# @brief      Python sandbox skill.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
"""Python sandbox skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.python_tool import python_execute

get_skill_registry().register(Skill(
    name="python-sandbox",
    display_name="Python Sandbox",
    description="Exécute du code Python pour calculs, analyses de données et scripts",
    icon="🐍",
    scopes=[],
    tools=[python_execute],
))
