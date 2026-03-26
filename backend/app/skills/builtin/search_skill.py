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
