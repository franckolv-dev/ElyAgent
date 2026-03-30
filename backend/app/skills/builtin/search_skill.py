# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Web Search skill — reliable search via Tavily or DuckDuckGo library (no Playwright scraping)."""
from app.skills.base import Skill
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
    tools=[web_search, web_search_news],
))
