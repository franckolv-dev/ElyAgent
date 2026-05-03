# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/knowledge_skill.py
# @brief      Knowledge Skill module
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
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.knowledge_tool import knowledge_search, knowledge_list

get_skill_registry().register(Skill(
    name="knowledge",
    display_name="Base de connaissances",
    description="Rechercher et consulter les documents personnels indexes",
    icon="📚",
    scopes=[],
    domains=[Domain.UNIVERSAL],
    tools=[knowledge_search, knowledge_list],
    enabled_by_default=True,
))
