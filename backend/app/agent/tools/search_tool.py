# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/search_tool.py
# @brief      Web search tool — Google-first strategy
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
"""Web search tool — Google-first strategy.

Priority order (first available key wins):
  1. Serper.dev          — Real Google results, 2 500 req/month free  (SERPER_API_KEY)
  2. Google Custom Search — Real Google results, 100 req/day free     (GOOGLE_SEARCH_API_KEY + GOOGLE_SEARCH_CX)
  3. Tavily              — Good quality, 1 000 req/month free          (TAVILY_API_KEY)
  4. DuckDuckGo          — Always available, no key, weaker on local   (fallback)

All backends use fr/France locale so local French results (restaurants,
shops, events…) are returned with correct regional relevance.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ── Result formatter ──────────────────────────────────────────────────────────

def _fmt_results(results: list[dict], query: str, source: str = "") -> str:
    if not results:
        return f"Aucun résultat trouvé pour : {query}"
    src = f" [{source}]" if source else ""
    lines = [f"Résultats Google{src} pour « {query} » ({len(results)} résultats) :"]
    for i, r in enumerate(results, 1):
        title   = r.get("title") or r.get("name") or "—"
        url     = r.get("url")   or r.get("href") or r.get("link") or ""
        snippet = r.get("content") or r.get("body") or r.get("snippet") or ""
        lines.append(f"\n{i}. {title}")
        if snippet:
            lines.append(f"   {snippet[:300]}")
        if url:
            lines.append(f"   {url}")
    return "\n".join(lines)


# ── Backend 1 : Serper.dev (Google results) ───────────────────────────────────

async def _search_serper(query: str, count: int, api_key: str) -> list[dict] | None:
    """Search via Serper.dev — returns real Google results. gl=fr, hl=fr."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "gl": "fr", "hl": "fr", "num": count},
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []
        # Knowledge graph (quick fact box) — prepend if present
        kg = data.get("knowledgeGraph", {})
        if kg.get("description"):
            results.append({
                "title": kg.get("title", ""),
                "url": kg.get("website", ""),
                "content": kg.get("description", ""),
            })
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", ""),
            })
            if len(results) >= count:
                break
        return results
    except Exception as exc:
        logger.warning("Serper search failed: %s", exc)
        return None


# ── Backend 2 : Google Custom Search JSON API ─────────────────────────────────

async def _search_google_cse(
    query: str, count: int, api_key: str, cx: str
) -> list[dict] | None:
    """Search via Google Programmable Search Engine API. gl=fr, hl=fr."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cx,
                    "q": query,
                    "gl": "fr",
                    "hl": "fr",
                    "num": min(count, 10),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", [])[:count]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", ""),
            })
        return results
    except Exception as exc:
        logger.warning("Google CSE search failed: %s", exc)
        return None


# ── Backend 3 : Tavily ────────────────────────────────────────────────────────

async def _search_tavily(query: str, count: int, api_key: str) -> list[dict] | None:
    try:
        from tavily import AsyncTavilyClient  # type: ignore
        client = AsyncTavilyClient(api_key=api_key)
        resp = await client.search(query, max_results=count)
        return resp.get("results") or []
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return None


# ── Backend 4 : DuckDuckGo (fallback, no key needed) ─────────────────────────

def _get_ddgs():
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
    DDGS = _get_ddgs()
    with DDGS() as ddgs:
        return ddgs.text(query, max_results=count, region="fr-fr", safesearch="off")


def _ddgs_news_sync(query: str, count: int) -> list[dict]:
    DDGS = _get_ddgs()
    with DDGS() as ddgs:
        return ddgs.news(query, max_results=count, region="fr-fr")


async def _search_ddgs(query: str, count: int) -> list[dict] | None:
    try:
        results = await asyncio.to_thread(_ddgs_text_sync, query, count)
        return list(results) if results else []
    except Exception as exc:
        logger.warning("DDGS search failed: %s", exc)
        return None


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def _dispatch_search(query: str, count: int) -> tuple[list[dict] | None, str]:
    """Try backends in priority order. Returns (results, source_name)."""
    from app.config import get_settings
    s = get_settings()

    serper_key: str = getattr(s, "serper_api_key", "") or ""
    gse_key: str    = getattr(s, "google_search_api_key", "") or ""
    gse_cx: str     = getattr(s, "google_search_cx", "") or ""
    tavily_key: str = getattr(s, "tavily_api_key", "") or ""

    if serper_key:
        results = await _search_serper(query, count, serper_key)
        if results is not None:
            return results, "Serper/Google"

    if gse_key and gse_cx:
        results = await _search_google_cse(query, count, gse_key, gse_cx)
        if results is not None:
            return results, "Google CSE"

    if tavily_key:
        results = await _search_tavily(query, count, tavily_key)
        if results is not None:
            return results, "Tavily"

    results = await _search_ddgs(query, count)
    return results, "DuckDuckGo"


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
async def web_search(
    query: str,
    count: int = 8,
) -> str:
    """Search the web (Google) and return the most relevant results.

    Always use this tool for any factual question, local business search,
    finding websites, restaurant recommendations, opening hours, etc.

    Args:
        query: Search query — always include city, region and country for local
               searches (e.g. 'pizzeria Chasseneuil-du-Poitou Vienne France').
               Use French for French topics, English for international topics.
        count: Number of results to return (1-10, default 8)
    """
    count = max(1, min(int(count), 10))
    results, source = await _dispatch_search(query, count)
    if results is not None:
        return _fmt_results(results, query, source)
    return (
        f"La recherche web a échoué pour « {query} ». "
        "Essaie browser_navigate avec une URL directe (ex: maps.google.fr, pagesjaunes.fr)."
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

    serper_key: str = getattr(s, "serper_api_key", "") or ""
    tavily_key: str = getattr(s, "tavily_api_key", "") or ""

    # Serper news
    if serper_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://google.serper.dev/news",
                    headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                    json={"q": query, "gl": "fr", "hl": "fr", "num": count},
                )
                resp.raise_for_status()
                data = resp.json()
            results = [
                {"title": n.get("title", ""), "url": n.get("link", ""), "content": n.get("snippet", "")}
                for n in data.get("news", [])[:count]
            ]
            if results:
                return _fmt_results(results, query, "Serper/Google News")
        except Exception as exc:
            logger.warning("Serper news failed: %s", exc)

    # Tavily news
    if tavily_key:
        try:
            from tavily import AsyncTavilyClient  # type: ignore
            client = AsyncTavilyClient(api_key=tavily_key)
            resp = await client.search(query, max_results=count, topic="news")
            results = resp.get("results") or []
            if results:
                return _fmt_results(results, query, "Tavily")
        except Exception as exc:
            logger.warning("Tavily news failed: %s", exc)

    # DDG news fallback
    try:
        results = await asyncio.to_thread(_ddgs_news_sync, query, count)
        return _fmt_results(list(results) if results else [], query, "DuckDuckGo")
    except Exception as exc:
        return f"Impossible de récupérer les actualités pour « {query} » : {exc}"
