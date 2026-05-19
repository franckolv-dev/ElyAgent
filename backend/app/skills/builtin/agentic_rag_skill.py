# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/agentic_rag_skill.py
# @brief      Agentic Rag Skill module
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
from app.skills.base import Skill
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
    tools=[smart_knowledge_query],
    enabled_by_default=True,
))
