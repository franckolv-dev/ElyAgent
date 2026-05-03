# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/search_skill.py
# @brief      Web Search skill — reliable search via Tavily or DuckDuckGo library (no Playwright scraping).
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
"""Web Search skill — reliable search via Tavily or DuckDuckGo library (no Playwright scraping)."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.search_tool import web_search, web_search_news

get_skill_registry().register(Skill(
    name="web_search",
    display_name="Recherche web",
    description=(
        "Recherche fiable sur le web via Tavily (si configuré) ou DuckDuckGo — "
        "sans scraping de navigateur, immunisé contre les blocages bot."
    ),
    icon="🔎",
    scopes=["internet"],
    domains=[Domain.RESEARCH],
    tools=[web_search, web_search_news],
))
