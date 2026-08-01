# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/search_tool.py
# @brief      Web search tool — Google-first strategy
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
        # Réponse réelle du 26/07 : {"message":"Not enough credits",...}
        detail = str(exc)
        try:
            detail += " " + resp.text  # noqa: F821 — présent si la réponse a été reçue
        except Exception:  # noqa: BLE001
            pass
        if is_quota_error(detail):
            mark_quota_exhausted("serper")
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


# ── Backend : SearchCans ──────────────────────────────────────────────────────
#
# Alternative moins chère à Serper, avec des crédits gratuits mensuels.
# Contrat relevé sur leur documentation (26/07) :
#   POST https://www.searchcans.com/api/v1/search
#   Authorization: Bearer <clé>
#   corps  : {"t": "google", "s": <requête>, "country", "language", "p"}
#   réponse: {"code": 0, "data": {"organic": [{title, link, snippet, …}],
#                                 "knowledgeGraph": {…}}}
# La forme est proche de Serper — le mapping ci-dessous en est le miroir.

async def _search_searchcans(query: str, count: int, api_key: str) -> list[dict] | None:
    """Search via SearchCans. Returns None on failure so the chain continues."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://www.searchcans.com/api/v1/search",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"t": "google", "s": query, "country": "fr",
                      "language": "fr", "p": 1, "knowledgeGraph": True},
            )
            resp.raise_for_status()
            payload = resp.json()

        # ⚠️ SearchCans annonce ses erreurs DANS LE CORPS, en HTTP 200 :
        #     {"code": -2011, "data": null, "msg": "API key has no balance"}
        # `raise_for_status()` passe donc, et sans ce contrôle le parseur rend
        # une liste VIDE que la chaîne lit comme un succès — elle s'arrête là
        # et n'essaie jamais Tavily. Incident du 31/07 : plus aucune recherche
        # ne remontait de résultat.
        code = payload.get("code")
        if code not in (None, 0):
            msg = str(payload.get("msg") or f"code {code}")
            logger.warning("SearchCans a refusé la requête : %s", msg)
            if is_quota_error(msg):
                mark_quota_exhausted("searchcans")
            return None

        data = payload.get("data") or {}
        results: list[dict] = []
        kg = data.get("knowledgeGraph") or {}
        if isinstance(kg, dict) and kg.get("description"):
            results.append({
                "title": kg.get("title", ""),
                "url": kg.get("website", "") or kg.get("link", ""),
                "content": kg.get("description", ""),
            })
        for item in data.get("organic") or []:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", ""),
            })
            if len(results) >= count:
                break
        return results
    except Exception as exc:
        logger.warning("SearchCans search failed: %s", exc)
        if is_quota_error(str(exc)):
            mark_quota_exhausted("searchcans")
        return None


# ── Disjoncteur de quota ──────────────────────────────────────────────────────
#
# Incident du 26/07 : le compte Serper était à court de crédits. Sans mémoire
# de cet état, CHAQUE recherche repayait un aller-retour vers un service dont
# on savait qu'il refuserait — de la latence pure, sur toutes les requêtes.
# L'oubli est volontairement court : Franck recharge, ça repart tout seul,
# sans redémarrer le backend.

_QUOTA_COOLDOWN_S = 1800  # 30 minutes
_quota_exhausted_at: dict[str, float] = {}

_QUOTA_MARKERS: tuple[str, ...] = (
    "not enough credits", "insufficient credit", "quota exceeded",
    "quota_exceeded", "out of credits", "rate limit exceeded",
    "payment required",
    # SearchCans dit « API key has no balance » (31/07). Sans ce motif, son
    # épuisement n'était pas reconnu et le disjoncteur ne l'écartait jamais.
    "no balance", "insufficient balance",
)


def is_quota_error(message: str) -> bool:
    """Le message d'erreur dit-il « plus de crédits / quota dépassé » ?"""
    low = (message or "").lower()
    return any(marker in low for marker in _QUOTA_MARKERS)


def mark_quota_exhausted(provider: str) -> None:
    import time as _t
    _quota_exhausted_at[provider] = _t.monotonic()
    logger.warning(
        "Recherche : %s à court de crédits — écarté pendant %d min",
        provider, _QUOTA_COOLDOWN_S // 60,
    )


def is_quota_exhausted(provider: str) -> bool:
    import time as _t
    stamp = _quota_exhausted_at.get(provider)
    if stamp is None:
        return False
    if _t.monotonic() - stamp > _QUOTA_COOLDOWN_S:
        _quota_exhausted_at.pop(provider, None)
        return False
    return True


def reset_quota_state() -> None:
    """Remet le disjoncteur à zéro (tests, ou reprise manuelle)."""
    _quota_exhausted_at.clear()


# ── Dispatcher ────────────────────────────────────────────────────────────────

# Suffixe posé sur le nom du fournisseur quand un moteur PRINCIPAL a échoué et
# qu'on est retombé sur le repli. Incident du 26/07 : le compte Serper était à
# court de crédits (« Not enough credits »), la chaîne est passée en silence
# sur DuckDuckGo — qui rend des pages d'accueil — et Ely a présenté ça comme
# un résultat de recherche normal, puis en a conclu que « les moteurs ne
# trouvent rien ». Le repli doit se voir.
_DEGRADED_SUFFIX = " (repli — moteur principal indisponible)"


def is_degraded(source: str) -> bool:
    """Le résultat vient-il d'un repli plutôt que du moteur principal ?"""
    src = (source or "").lower()
    return _DEGRADED_SUFFIX.strip().lower() in src or src.startswith("duckduckgo")

async def _dispatch_search(query: str, count: int) -> tuple[list[dict] | None, str]:
    """Try backends in priority order. Returns (results, source_name)."""
    from app.config import get_settings
    s = get_settings()

    serper_key: str = getattr(s, "serper_api_key", "") or ""
    gse_key: str    = getattr(s, "google_search_api_key", "") or ""
    gse_cx: str     = getattr(s, "google_search_cx", "") or ""
    tavily_key: str = getattr(s, "tavily_api_key", "") or ""

    # ⚠️ Dans une cascade de replis, « zéro résultat » n'est PAS une réponse :
    # c'est un motif pour essayer le suivant. On teste donc la vérité de la
    # liste (`if results:`) et non `is not None`.
    #
    # Incident du 31/07 : SearchCans, à court de crédits, rendait `[]`. La
    # chaîne le lisait comme un succès, s'arrêtait, et n'atteignait jamais
    # Tavily — qui fonctionnait. Un fournisseur qui répond poliment vide est
    # plus dangereux qu'un fournisseur qui plante.
    _primary_failed = False

    if serper_key and not is_quota_exhausted("serper"):
        results = await _search_serper(query, count, serper_key)
        if results:
            return results, "Serper/Google"
        _primary_failed = True
    elif serper_key:
        _primary_failed = True  # écarté : crédits épuisés

    searchcans_key: str = getattr(s, "searchcans_api_key", "") or ""
    if searchcans_key and not is_quota_exhausted("searchcans"):
        results = await _search_searchcans(query, count, searchcans_key)
        if results:
            return results, "SearchCans"
        _primary_failed = True
    elif searchcans_key:
        _primary_failed = True

    if gse_key and gse_cx:
        results = await _search_google_cse(query, count, gse_key, gse_cx)
        if results:
            return results, "Google CSE"

    if tavily_key:
        results = await _search_tavily(query, count, tavily_key)
        if results:
            return results, "Tavily"

    results = await _search_ddgs(query, count)
    return results, "DuckDuckGo" + (_DEGRADED_SUFFIX if _primary_failed else "")


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
        formatted = _fmt_results(results, query, source)
        if is_degraded(source):
            # Dire au modèle CE QUI se passe, plutôt que de le laisser
            # conclure que « le web ne contient rien ».
            formatted += (
                "\n\n⚠️ Recherche DÉGRADÉE : le moteur principal est "
                "indisponible (clé absente, quota ou crédits épuisés) et ces "
                "résultats viennent du repli, qui renvoie souvent des pages "
                "d'accueil plutôt que des articles. Ne conclus pas que le "
                "sujet n'existe pas. Pour de l'actualité récente, utilise "
                "web_search_news ou news_get_headlines ; sinon ouvre une "
                "source directement avec browser_navigate puis "
                "browser_tab_read_text, et signale à l'utilisateur que sa "
                "recherche web est dégradée."
            )
        return formatted
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
