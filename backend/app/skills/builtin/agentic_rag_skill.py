# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/agentic_rag_skill.py
# @brief      Agentic Rag Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
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
from app.agent.tools.agentic_rag_tool import smart_knowledge_query

get_skill_registry().register(Skill(
    name="agentic_rag",
    display_name="Recherche documentaire intelligente",
    description=(
        "Recherche proactive dans les documents personnels avec detection "
        "de pertinence et reranking document-level"
    ),
    icon="🧠",
    scopes=[],
    domains=[Domain.UNIVERSAL],
    tools=[smart_knowledge_query],
    enabled_by_default=True,
))
