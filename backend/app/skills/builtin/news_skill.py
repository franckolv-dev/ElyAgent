# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/news_skill.py
# @brief      News skill — latest headlines via Google News RSS
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
"""News skill — latest headlines via Google News RSS.

No API key required.  Uses the public Google News RSS feed which supports
language/region targeting and free-text topic queries.

The RSS XML is parsed with Python's stdlib xml.etree so no extra
dependency is required.
"""
from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

from langchain_core.tools import tool

from app.skills.base import Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

_RSS_BASE = "https://news.google.com/rss"
_HEADERS = {"User-Agent": "ELY-Agent/1.0"}


def _parse_rss(xml_text: str, count: int) -> list[dict]:
    """Extract title + source + pubDate from an RSS 2.0 feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item")[:count]:
        raw_title = item.findtext("title", "").strip()
        # Google News titles are "Article title - Source Name"
        # Split on the last " - " to separate headline from source
        if " - " in raw_title:
            *parts, source = raw_title.rsplit(" - ", 1)
            title = " - ".join(parts).strip()
        else:
            title, source = raw_title, ""
        pub_date = item.findtext("pubDate", "")[:25]  # trim timezone verbosity
        items.append({"title": title, "source": source, "date": pub_date})
    return items


@tool
async def news_get_headlines(query: str = "", count: int = 5, language: str = "fr") -> str:
    """Get the latest news headlines, optionally filtered by a topic or keyword.

    Args:
        query: Topic to search for (leave empty for top headlines).
               Examples: 'intelligence artificielle', 'Paris', 'football', 'économie'
        count: Number of articles to return (1-10, default 5)
        language: Language/country code — 'fr' (default), 'en', 'es', 'de', etc.
    """
    import httpx

    count = max(1, min(int(count), 10))
    lang_map = {
        "fr": ("fr", "FR", "FR:fr"),
        "en": ("en", "US", "US:en"),
        "es": ("es", "ES", "ES:es"),
        "de": ("de", "DE", "DE:de"),
        "it": ("it", "IT", "IT:it"),
    }
    hl, gl, ceid = lang_map.get(language, ("fr", "FR", "FR:fr"))

    try:
        if query.strip():
            import urllib.parse
            q = urllib.parse.quote(query.strip())
            url = f"{_RSS_BASE}/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
            label = f"Actualités — {query}"
        else:
            url = f"{_RSS_BASE}?hl={hl}&gl={gl}&ceid={ceid}"
            label = "À la une"

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()

        articles = _parse_rss(resp.text, count)
        if not articles:
            return "Aucune actualité trouvée."

        lines = [f"{label} ({len(articles)} articles) :"]
        for a in articles:
            source = f" — {a['source']}" if a["source"] else ""
            lines.append(f"• {a['title']}{source}")

        return "\n".join(lines)

    except Exception as exc:
        logger.warning("news_get_headlines failed: %s", exc)
        return f"Impossible de récupérer les actualités : {exc}"


get_skill_registry().register(Skill(
    name="news",
    display_name="Actualités",
    description="Dernières actualités et titres de presse via Google News (sans clé API)",
    icon="📰",
    scopes=["internet"],
    tools=[news_get_headlines],
))
