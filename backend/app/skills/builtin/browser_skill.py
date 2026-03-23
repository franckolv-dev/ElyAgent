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

from app.skills.base import Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

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
    count: int = 5,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search the web via DuckDuckGo and return the top results with titles, snippets and URLs.

    Prefer this over browser_navigate when you need to find information
    on a topic rather than read a specific page.

    Args:
        query: Search query (in any language)
        count: Number of results to return (1-10, default 5)
    """
    from app.services.browser_manager import get_browser_manager

    count = max(1, min(int(count), 10))

    try:
        mgr = get_browser_manager()
        page = await mgr.get_page(user_id or "default")

        q = urllib.parse.quote_plus(query)
        await page.goto(
            f"https://html.duckduckgo.com/html/?q={q}&kl=fr-fr",
            wait_until="domcontentloaded",
            timeout=20_000,
        )

        results = await page.evaluate(f"""() => {{
            const items = document.querySelectorAll('.result');
            return Array.from(items).slice(0, {count}).map(item => {{
                const a = item.querySelector('.result__title a');
                const snip = item.querySelector('.result__snippet');
                const href = a ? a.getAttribute('href') : '';
                // DuckDuckGo wraps links — extract actual URL from uddg= param
                let url = href;
                try {{
                    const params = new URLSearchParams(new URL('https://x.com' + href).search);
                    if (params.get('uddg')) url = decodeURIComponent(params.get('uddg'));
                }} catch(_) {{}}
                return {{
                    title:   a    ? a.innerText.trim()    : '',
                    snippet: snip ? snip.innerText.trim() : '',
                    url,
                }};
            }}).filter(r => r.title);
        }}""")

        if not results:
            return f"Aucun résultat DuckDuckGo pour : {query}"

        lines = [f"Résultats de recherche pour « {query} » ({len(results)} résultats) :"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:200]}")
            if r.get("url"):
                lines.append(f"   {r['url']}")

        return "\n".join(lines)

    except Exception as exc:
        logger.warning("browser_search_web error: %s", exc)
        return f"Erreur de recherche web : {exc}"


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
    """Take a screenshot of the current browser page and save it to a file.

    Returns the file path.  Useful to inspect the visual state of a page
    after navigation or interaction.
    """
    from app.services.browser_manager import get_browser_manager

    try:
        mgr = get_browser_manager()
        path = await mgr.screenshot_path(user_id or "default")
        page = await mgr.get_page(user_id or "default")
        title = await page.title()
        return f"Capture d'écran enregistrée : {path}\nPage : {title}"

    except Exception as exc:
        logger.warning("browser_screenshot error: %s", exc)
        return f"Erreur lors de la capture d'écran : {exc}"


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
    tools=[
        browser_navigate,
        browser_search_web,
        browser_get_text,
        browser_screenshot,
        browser_click,
        browser_fill,
        browser_close,
    ],
))
