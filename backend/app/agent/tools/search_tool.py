"""Web search tool — reliable search without headless browser scraping.

Strategy (tried in order):
  1. Tavily Search API  — best quality, structured results, optional (needs TAVILY_API_KEY)
  2. DuckDuckGo DDGS    — free, no key, uses proper HTTP client (not Playwright scraping)

Both backends are immune to the bot-detection issues that affect headless Playwright
against html.duckduckgo.com.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _fmt_results(results: list[dict], query: str) -> str:
    if not results:
        return f"Aucun résultat trouvé pour : {query}"
    lines = [f"Résultats de recherche pour « {query} » ({len(results)} résultats) :"]
    for i, r in enumerate(results, 1):
        title   = r.get("title") or r.get("name") or "—"
        url     = r.get("url")   or r.get("href") or ""
        snippet = r.get("content") or r.get("body") or r.get("snippet") or ""
        lines.append(f"\n{i}. {title}")
        if snippet:
            lines.append(f"   {snippet[:250]}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


async def _search_tavily(query: str, count: int, api_key: str) -> list[dict] | None:
    """Search via Tavily API. Returns None if the key is absent or the call fails."""
    try:
        from tavily import AsyncTavilyClient  # type: ignore
        client = AsyncTavilyClient(api_key=api_key)
        resp = await client.search(query, max_results=count)
        return resp.get("results") or []
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return None


def _get_ddgs():
    """Import DDGS — try the new 'ddgs' package first, fall back to 'duckduckgo_search'."""
    try:
        from ddgs import DDGS  # type: ignore
        return DDGS
    except ImportError:
        pass
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from duckduckgo_search import DDGS  # type: ignore
    return DDGS


def _ddgs_text_sync(query: str, count: int) -> list[dict]:
    """Synchronous DuckDuckGo text search — run via asyncio.to_thread."""
    DDGS = _get_ddgs()
    with DDGS() as ddgs:
        return ddgs.text(query, max_results=count, region="fr-fr", safesearch="off")


def _ddgs_news_sync(query: str, count: int) -> list[dict]:
    """Synchronous DuckDuckGo news search — run via asyncio.to_thread."""
    DDGS = _get_ddgs()
    with DDGS() as ddgs:
        return ddgs.news(query, max_results=count, region="fr-fr")


async def _search_ddgs(query: str, count: int) -> list[dict] | None:
    """Search via duckduckgo-search library (no Playwright, proper HTTP client).

    Runs the synchronous DDGS API in a thread pool to avoid blocking the event loop.
    """
    import asyncio
    try:
        results = await asyncio.to_thread(_ddgs_text_sync, query, count)
        return list(results) if results else []
    except Exception as exc:
        logger.warning("DDGS search failed: %s", exc)
        return None


@tool
async def web_search(
    query: str,
    count: int = 8,
) -> str:
    """Search the web and return the most relevant results (titles, snippets, URLs).

    Uses Tavily (if configured) or DuckDuckGo as backend — much more reliable
    than browser-based scraping.  Prefer this for any factual question, news,
    finding websites, local businesses, etc.

    Args:
        query: Search query — be precise, include location/country if relevant
               (e.g. 'restaurant Le Moulin Chasseneuil du Poitou 86360 France site officiel')
        count: Number of results to return (1-10, default 8)
    """
    from app.config import get_settings
    count = max(1, min(int(count), 10))
    s = get_settings()
    tavily_key: str = getattr(s, "tavily_api_key", "") or ""

    # 1. Try Tavily if configured
    if tavily_key:
        results = await _search_tavily(query, count, tavily_key)
        if results is not None:
            return _fmt_results(results, query)

    # 2. Fall back to DuckDuckGo library
    results = await _search_ddgs(query, count)
    if results is not None:
        return _fmt_results(results, query)

    return (
        f"La recherche web a échoué pour « {query} ». "
        "Essaie browser_navigate avec une URL directe si tu la connais."
    )


@tool
async def web_search_news(
    query: str,
    count: int = 5,
) -> str:
    """Search recent news articles on a topic.

    Args:
        query: News topic to search
        count: Number of articles to return (1-10, default 5)
    """
    from app.config import get_settings
    count = max(1, min(int(count), 10))
    s = get_settings()
    tavily_key: str = getattr(s, "tavily_api_key", "") or ""

    if tavily_key:
        try:
            from tavily import AsyncTavilyClient  # type: ignore
            client = AsyncTavilyClient(api_key=tavily_key)
            resp = await client.search(query, max_results=count, topic="news")
            results = resp.get("results") or []
            if results:
                return _fmt_results(results, query)
        except Exception as exc:
            logger.warning("Tavily news search failed: %s", exc)

    # DDGS news fallback
    import asyncio
    try:
        results = await asyncio.to_thread(_ddgs_news_sync, query, count)
        return _fmt_results(list(results) if results else [], query)
    except Exception as exc:
        logger.warning("DDGS news search failed: %s", exc)
        return f"Impossible de récupérer les actualités pour « {query} » : {exc}"
