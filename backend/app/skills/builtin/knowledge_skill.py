# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/knowledge_skill.py
# @brief      Knowledge Skill module
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
