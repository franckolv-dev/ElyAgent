# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/browser_skill.py
# @brief      Browser control skill — Playwright headless Chromium
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
"""Browser control skill — Playwright headless Chromium.

Tools
-----
browser_navigate      Load a URL and return its text content
browser_search_web    Search DuckDuckGo and return the top results
browser_get_text      Extract text from a CSS selector on the current page
browser_screenshot    Save a screenshot and return the file path
browser_click         Click an element
browser_fill          Fill a form field

Ni l'un ni l'autre ne demande d'accord par défaut — décision de Franck du
28/07 (`APPROVAL_WAIVED`) : « naviguer n'est pas engager », « remplir un
formulaire n'est pas le soumettre ». HITL se déclenche sur le CONTENU des
arguments, pas sur le nom de l'outil : un parcours d'achat (`checkout`,
`panier`, `paypal.com`, `amazon.`…) passe par `_CRITICAL_KEYWORDS`.
browser_close         Close the user's browser session

All tools receive ``user_id`` via InjectedToolArg so each user has their
own isolated browser context (no cross-user cookie or storage leakage).

Content extraction strategy
----------------------------
``browser_navigate`` tries semantic selectors in priority order:
  article → main → [role="main"] → .content → #content → body
Scripts, styles, nav, footer, ads and sidebars are stripped before
returning text.  Content is capped at 5 000 characters.

Le texte rendu par ``browser_navigate`` et ``browser_get_text`` est du
contenu TIERS : il part encadré (``services/external_content``), comme celui
de ``web_extract``. Le titre et l'URL courante viennent de la page eux aussi
et passent par ``etiquette_externe``.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.external_content import etiquette_externe, wrap_external
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

        if ws_registry.get(user_id) is None:
            return  # user not connected — nothing to push

        png_bytes = await page.screenshot(full_page=False)
        b64 = base64.b64encode(png_bytes).decode("utf-8")

        await ws_registry.send_text_all(user_id, json.dumps({
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


def _truncate(text: str, limit: int = 5000, *, origin: str = "") -> str:
    """Borne un texte de page et l'ENCADRE. Renvoie le cadre, note comprise.

    ⚠️ CE QUE ÇA CORRIGE (relecture du 02/09/2026) : la surface « web » n'était
    fermée qu'à moitié. `web_extract` encadrait son texte, mais
    `browser_navigate` et `browser_get_text` — le MÊME Playwright, et la voie
    DOCUMENTÉE pour « lire un article » — le rendaient nu. Un attaquant n'avait
    qu'à faire choisir cet outil-là.

    L'annonce de troncature, elle, reste HORS du cadre : elle vient d'Ely, et
    une consigne d'Ely encadrée en « non fiable » serait ignorée par le modèle
    au moment même où elle lui dit quoi faire.
    """
    cadre = wrap_external(text[:limit], source="page web", origin=origin or None)
    if len(text) <= limit:
        return cadre
    return cadre + "\n\n[… contenu tronqué — utilise browser_get_text avec un sélecteur plus précis]"


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

        # Le titre est écrit par la page et l'URL courante est celle où la
        # page a fini par emmener le navigateur (redirections comprises) :
        # tiers tous les deux, donc mis à plat et neutralisés avant d'être
        # rendus en tête, là où le modèle lit les repères d'Ely.
        return (
            f"Page : {etiquette_externe(title)}\n"
            f"URL  : {etiquette_externe(current_url)}\n\n"
            + _truncate(content, origin=current_url)
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
        return _truncate(text.strip(), limit=3000, origin=page.url)

    except Exception as exc:
        logger.warning("browser_get_text error: %s", exc)
        return f"Erreur lors de l'extraction du texte ({selector}) : {exc}"


@tool
async def browser_screenshot(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Capture la page web courante. **N'envoie PAS le fichier** — chaîne avec un autre outil.

    Retourne un JSON contenant ``local_path`` (fichier PNG sur disque) et
    ``attachment_id``. **Tu DOIS ensuite appeler l'un des outils suivants
    selon l'intention de l'utilisateur** — ne te contente jamais d'écrire
    « j'envoie… » ou « je sauvegarde… » en prose, ce sont des promesses
    sans effet :

    📤 ÉTAPES SUIVANTES OBLIGATOIRES :

    • **Afficher la capture dans le chat** : ajoute la ligne
      ``MEDIA:<local_path>`` dans ta réponse texte (le backend extrait
      cette ligne et affiche l'image au user, même si tu n'appelles
      aucun autre outil). Exemple : ``MEDIA:/tmp/ely-attachments/screenshot-abc123.png``.

    • **Envoyer par mail** : appelle
      ``gmail_send_with_local_attachment(to=..., subject=..., body=...,
      local_path=<local_path>)``.

    • **Sauvegarder sur Google Drive** : appelle
      ``drive_upload_local_file(local_path=<local_path>, name=...)``.
      (⚠️ PAS ``drive_create_file`` — celui-ci n'écrit que du TEXTE, il ne
      peut pas téléverser un PNG.)

    • **Sauvegarder sur le poste local** : si l'utilisateur fournit un
      chemin précis, appelle ``desktop_copy_file(src=<local_path>,
      dst=<chemin user>)``. Le fichier ``local_path`` retourné par cet
      outil vit dans ``/tmp/ely-attachments/`` côté serveur — le user
      ne le voit pas tant que tu ne déclenches pas une livraison.

    ❌ INTERDICTIONS strictes :
    • Ne PROMETS jamais une livraison sans appeler l'outil correspondant.
    • Ne dis jamais « En cours : téléchargement… » sans tool call actif.
    • Ne hallucine pas un chemin Drive — si tu n'appelles pas
      ``drive_upload_local_file``, le fichier n'est PAS sur le Drive.

    Returns
    -------
    JSON string avec keys: ``local_path``, ``attachment_id``, ``prompt``,
    ``data`` (base64), ``mime``.
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

        # FIX 2026-05-06: aussi sauvegarder sur disque pour que d'autres
        # tools (gmail_send_with_local_attachment, etc.) puissent chaîner
        # sur ce fichier sans repasser par Drive. Sans cette sauvegarde,
        # impossible d'envoyer une capture par mail (architectural gap).
        # Le fichier vit dans /tmp (éphémère, purgé au reboot du container).
        import os
        import uuid as _uuid
        attach_dir = "/tmp/ely-attachments"
        try:
            os.makedirs(attach_dir, mode=0o700, exist_ok=True)
            attachment_id = _uuid.uuid4().hex[:12]
            local_path = f"{attach_dir}/screenshot-{attachment_id}.png"
            with open(local_path, "wb") as f:
                f.write(png_bytes)
        except Exception as _save_exc:
            logger.warning("browser_screenshot: failed to save to disk (%s) — base64-only mode", _save_exc)
            local_path = ""
            attachment_id = ""

        # FIX 2026-05-06 (Hermes-style): inclure le mode d'emploi des
        # next-steps dans le retour JSON. Les modèles faibles (Ministral,
        # Qwen 8B, etc.) ne respectent pas toujours la docstring mais
        # lisent le tool result. Y mettre les instructions explicites
        # divise par 5 le taux d'hallucination « j'envoie sur Drive » sans
        # appel d'outil réel.
        next_steps = (
            f"Capture sauvegardée. Pour livrer le fichier au user, "
            f"applique l'UNE des actions suivantes :\n"
            f"  • Afficher dans le chat → ajoute la ligne 'MEDIA:{local_path}' "
            f"à ta prochaine réponse texte.\n"
            f"  • Envoyer par mail → appelle gmail_send_with_local_attachment("
            f"local_path='{local_path}', to=..., subject=..., body=...).\n"
            f"  • Uploader sur Drive → appelle drive_upload_local_file("
            f"local_path='{local_path}', name=...).\n"
            f"  • Copier sur le poste user → desktop_copy_file("
            f"src='{local_path}', dst=<chemin demandé>).\n"
            f"NE DIS JAMAIS 'téléchargement en cours' / 'envoi en cours' "
            f"sans avoir appelé l'un de ces outils."
        ) if local_path else "Capture en mémoire seulement (échec sauvegarde disque)."

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"Capture d'écran — {title} ({page.url})",
            # Pour chaîner avec gmail_send_with_local_attachment, etc.
            "local_path": local_path,
            "attachment_id": attachment_id,
            # Instructions explicites lues par le LLM
            "next_steps": next_steps,
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
# Aiguillage vers la session de l'utilisateur                          #
# ------------------------------------------------------------------ #
#
# Ces outils pilotent un Chromium headless côté serveur : aucun cookie,
# aucune session. Sur tout site derrière authentification, ils rendent la
# page de connexion — et le modèle en déduit que le site est inaccessible.
#
# L'extension navigateur, elle, pilote le VRAI Chrome de l'utilisateur, déjà
# connecté (``browser_open_tab`` / ``browser_tab_read_text``). Les deux
# familles sont bindées et ne diffèrent que d'un mot dans leur nom : sans cet
# avertissement, le modèle choisit le nom le plus évident, qui est le mauvais.

_NO_SESSION_NOTICE = (
    "\n\nNOTE: headless, NO login session — sites behind authentication "
    "(LinkedIn, Doctolib, Gmail…) return the login page. For those use "
    "browser_open_tab + browser_tab_read_text, which drive the user's own "
    "signed-in Chrome."
)

for _sessionless in (browser_navigate, browser_get_text, browser_screenshot):
    _sessionless.description += _NO_SESSION_NOTICE


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
