# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/browser_skill.py
# @brief      Browser control skill — Playwright headless Chromium
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
"""Browser control skill — Playwright headless Chromium.

Tools
-----
browser_navigate      Load a URL and return its text content
browser_search_web    Search DuckDuckGo and return the top results
browser_get_text      Extract text from a CSS selector on the current page
browser_screenshot    Save a screenshot and return the file path
browser_click         Click an element (⚠ HITL required)
browser_fill          Fill a form field (⚠ HITL required)
browser_close         Close the user's browser session

All tools receive ``user_id`` via InjectedToolArg so each user has their
own isolated browser context (no cross-user cookie or storage leakage).

Content extraction strategy
----------------------------
``browser_navigate`` tries semantic selectors in priority order:
  article → main → [role="main"] → .content → #content → body
Scripts, styles, nav, footer, ads and sidebars are stripped before
returning text.  Content is capped at 5 000 characters.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


async def _push_browser_frame(page, user_id: str) -> None:
    """Send a live screenshot of *page* to the user's WebSocket as a ``browser_frame`` message.

    Called silently after every browser action (navigate, click, fill) so the
    frontend can render a live view of the browser session.  Failures are
    swallowed — the main tool result is what matters.
    """
    try:
        import base64
        import json
        from app.services import ws_registry

        ws = ws_registry.get(user_id)
        if ws is None:
            return  # user not connected — nothing to push

        png_bytes = await page.screenshot(full_page=False)
        b64 = base64.b64encode(png_bytes).decode("utf-8")

        await ws.send_text(json.dumps({
            "type": "browser_frame",
            "data": b64,
            "url": page.url,
            "title": await page.title(),
        }))
    except Exception as exc:
        logger.debug("_push_browser_frame silently failed: %s", exc)


# JS helper injected into every content-extraction call
_EXTRACT_JS = """() => {
    const PRIORITY = ['article', 'main', '[role="main"]', '.content',
                      '#content', '#main', '.post-content', '.entry-content'];
    for (const sel of PRIORITY) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const clone = el.cloneNode(true);
        clone.querySelectorAll(
            'script,style,nav,footer,header,aside,.ad,.ads,.advertisement,' +
            '.cookie-banner,.sidebar,.social-share'
        ).forEach(n => n.remove());
        const txt = clone.innerText.replace(/\\n{3,}/g, '\\n\\n').trim();
        if (txt.length > 200) return txt;
    }
    const body = document.body.cloneNode(true);
    body.querySelectorAll('script,style,nav,footer,header,aside').forEach(n => n.remove());
    return body.innerText.replace(/\\n{3,}/g, '\\n\\n').trim();
}"""


def _truncate(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[… contenu tronqué — utilise browser_get_text avec un sélecteur plus précis]"


# ------------------------------------------------------------------ #
# Tools                                                                #
# ------------------------------------------------------------------ #

@tool
async def browser_navigate(
    url: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Load a URL in the headless browser and return the page text content.

    Best for reading articles, product pages, documentation, etc.
    The URL stays open — subsequent browser tools operate on this page.

    Args:
        url: Full URL to navigate to (http:// or https://)
    """
    from app.services.browser_manager import get_browser_manager

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wait a moment for JS-rendered content
        await page.wait_for_timeout(1_000)

        title = await page.title()
        current_url = page.url
        content = await page.evaluate(_EXTRACT_JS)

        # Push a live screenshot to the frontend (fire-and-forget)
        await _push_browser_frame(page, user_id)

        return (
            f"Page : {title}\n"
            f"URL  : {current_url}\n\n"
            + _truncate(content)
        )

    except Exception as exc:
        logger.warning("browser_navigate error: %s", exc)
        return f"Erreur lors de la navigation vers {url} : {exc}"


@tool
async def browser_search_web(
    query: str,
    count: int = 8,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search the web and return the top results with titles, snippets and URLs.

    Uses the DuckDuckGo Python library (not Playwright scraping) — immune to bot detection.
    Falls back to Tavily if TAVILY_API_KEY is configured.

    Prefer web_search over this tool — they share the same backend.
    Use browser_navigate when you need to read a specific page in full.

    Args:
        query: Search query (in any language)
        count: Number of results to return (1-10, default 8)
    """
    # Delegate entirely to the reliable search_tool backend (no Playwright scraping)
    from app.agent.tools.search_tool import web_search as _web_search
    return await _web_search.ainvoke({"query": query, "count": count})


@tool
async def browser_get_text(
    selector: str = "body",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Extract the visible text of a specific element on the current browser page.

    Use this to focus on a specific section after ``browser_navigate``.

    Args:
        selector: CSS selector (e.g. 'h1', '.price', '#description', 'table')
    """
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        element = await page.query_selector(selector)
        if not element:
            return f"Aucun élément trouvé pour le sélecteur : {selector!r}"

        text = await element.inner_text()
        return _truncate(text.strip(), limit=3000)

    except Exception as exc:
        logger.warning("browser_get_text error: %s", exc)
        return f"Erreur lors de l'extraction du texte ({selector}) : {exc}"


@tool
async def browser_screenshot(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Take a screenshot of the current browser page and display it inline in the chat.

    Useful to inspect the visual state of a page after navigation or interaction.
    """
    import base64
    import json
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")
        title = await page.title()

        png_bytes = await page.screenshot(full_page=False)
        b64 = base64.b64encode(png_bytes).decode("utf-8")

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"Capture d'écran — {title} ({page.url})",
        })

    except Exception as exc:
        logger.warning("browser_screenshot error: %s", exc)
        return f"Erreur lors de la capture d'écran : {exc}"


@tool
async def browser_search_images(
    query: str,
    count: int = 3,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search Google Images and display results inline in the chat.

    Use this when the user asks to find, show or display an image of something.
    Do NOT use generate_image for this — use this tool to find real photos.

    Args:
        query: Description of the image to search for (e.g. 'boeuf charolais', 'tour eiffel nuit')
        count: Number of images to return (1-4, default 3)
    """
    import base64
    import json
    import httpx

    count = max(1, min(int(count), 4))

    try:
        from app.services.browser_manager import get_browser_manager
        mgr  = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        q = urllib.parse.quote_plus(query)
        await page.goto(
            f"https://www.google.com/search?q={q}&tbm=isch&hl=fr",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        await page.wait_for_timeout(2000)

        # Extraire les URLs des thumbnails Google Images
        img_urls: list[str] = await page.evaluate("""(count) => {
            const imgs = Array.from(document.querySelectorAll('img'));
            const results = [];
            for (const img of imgs) {
                const src = img.src || img.getAttribute('data-src') || '';
                // Filtrer : garder seulement les vraies photos (pas les icônes Google)
                if (src.startsWith('data:image') && src.length > 500) {
                    results.push(src);
                } else if (src.startsWith('http') && !src.includes('google.com/images/branding')) {
                    results.push(src);
                }
                if (results.length >= count * 3) break;
            }
            return results;
        }""", count)

        if not img_urls:
            return f"Aucune image trouvée sur Google pour : {query}"

        images = []
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            for src in img_urls:
                if len(images) >= count:
                    break
                try:
                    if src.startswith("data:image"):
                        # Déjà en base64 (thumbnail Google)
                        header, b64 = src.split(",", 1)
                        mime = header.split(";")[0].replace("data:", "")
                        if len(b64) > 500:
                            images.append({"data": b64, "mime": mime, "title": query})
                    else:
                        resp = await client.get(src)
                        if resp.status_code == 200 and len(resp.content) > 2000:
                            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                            if mime.startswith("image/"):
                                b64 = base64.b64encode(resp.content).decode("utf-8")
                                images.append({"data": b64, "mime": mime, "title": query})
                except Exception:
                    continue

        if not images:
            return f"J'ai trouvé des résultats Google mais impossible de récupérer les images pour : {query}"

        return json.dumps({
            "type": "images",
            "items": images,
            "query": query,
        })

    except Exception as exc:
        logger.warning("browser_search_images error: %s", exc)
        return f"Erreur lors de la recherche d'images pour « {query} » : {exc}"


@tool
async def browser_click(
    selector: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Click an element on the current browser page.

    ⚠️ This action ALWAYS requires human validation before executing.

    Accepts a CSS selector OR the visible text of a button/link.
    Examples: '#submit-btn', 'button:has-text("Valider")', 'a:has-text("Connexion")'

    Args:
        selector: CSS selector or text-based selector of the element to click
    """
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        await page.click(selector, timeout=10_000)
        await page.wait_for_timeout(800)  # wait for navigation/reaction

        title = await page.title()

        # Push a live screenshot to the frontend (fire-and-forget)
        await _push_browser_frame(page, user_id)

        return f"Clic effectué sur {selector!r}. Page actuelle : {title} ({page.url})"

    except Exception as exc:
        logger.warning("browser_click error: %s", exc)
        return f"Erreur lors du clic sur {selector!r} : {exc}"


@tool
async def browser_fill(
    selector: str,
    value: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Fill a form field (input, textarea) on the current browser page.

    ⚠️ This action ALWAYS requires human validation before executing.

    Args:
        selector: CSS selector of the input field (e.g. '#email', 'input[name="q"]')
        value: Text value to enter into the field
    """
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        await page.fill(selector, value, timeout=10_000)

        # Push a live screenshot to the frontend (fire-and-forget)
        await _push_browser_frame(page, user_id)

        return f"Champ {selector!r} rempli avec la valeur : {value!r}"

    except Exception as exc:
        logger.warning("browser_fill error: %s", exc)
        return f"Erreur lors du remplissage du champ {selector!r} : {exc}"


@tool
async def browser_close(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Close the browser session for the current user and free memory.

    Call this when finished with browser tasks to release resources.
    """
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        await mgr.close_session(user_id or "default")
        return "Session navigateur fermée."
    except Exception as exc:
        return f"Erreur lors de la fermeture du navigateur : {exc}"


# ------------------------------------------------------------------ #
# Skill registration                                                   #
# ------------------------------------------------------------------ #

get_skill_registry().register(Skill(
    name="browser",
    display_name="Navigateur web",
    description=(
        "Contrôle un navigateur Chromium headless : naviguer, chercher sur le web, "
        "lire des pages, remplir des formulaires et cliquer (click/fill requièrent validation)"
    ),
    icon="🌍",
    scopes=["internet"],
    domains=[Domain.RESEARCH],
    tools=[
        browser_navigate,
        browser_search_web,
        browser_search_images,
        browser_get_text,
        browser_screenshot,
        browser_click,
        browser_fill,
        browser_close,
    ],
))
