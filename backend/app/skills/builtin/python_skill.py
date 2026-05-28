# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/python_skill.py
# @brief      Python sandbox skill.
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Python sandbox skill."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.python_tool import python_execute

get_skill_registry().register(Skill(
    name="python-sandbox",
    display_name="Python Sandbox",
    description="Exécute du code Python pour calculs, analyses de données et scripts",
    icon="🐍",
    scopes=[],
    domains=[Domain.CREATIVE, Domain.DATA],
    tools=[python_execute],
))
