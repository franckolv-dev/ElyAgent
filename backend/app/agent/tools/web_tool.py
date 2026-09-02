# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/web_tool.py
# @brief      Automatisation web SANS navigateur ouvert — capture, PDF,
#             extraction, comparaison. Une URL entre, un résultat sort.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Quatre outils « un coup » : une URL entre, un résultat sort.

POURQUOI ILS EXISTENT À CÔTÉ DE ``browser_*``
----------------------------------------------
``browser_screenshot`` et ``browser_get_text`` agissent sur la page COURANTE
d'un utilisateur. Ils supposent un ``browser_navigate`` préalable et laissent
la page où ils l'ont mise. C'est exactement ce qu'il faut pour explorer un
site à deux, l'agent et l'humain regardant la même chose.

Une tâche planifiée n'a rien de tout ça :

- elle tourne **sans personne devant** — il n'y a pas de « page courante » ;
- elle peut tourner **pendant** que l'utilisateur navigue : réutiliser sa
  session la lui déplacerait sous les yeux, et le résultat de la tâche
  dépendrait de l'endroit où il l'a laissée ;
- elle veut **un résultat, pas une conversation** : `navigate` puis
  `screenshot` fait deux tours de modèle là où un seul suffit.

D'où ces quatre-là, tous bâtis sur ``BrowserManager.one_shot_page`` : contexte
créé, utilisé, fermé. Le navigateur est partagé, le contexte ne l'est pas.

⚠️ LE CHOIX EST DIT DANS LES DESCRIPTIONS. Deux familles proches dans un
catalogue de ~145 outils, c'est une occasion de se tromper. Chaque docstring
dit en première ligne pour quel usage elle est faite, et nomme l'autre.

CE QU'ILS NE FONT PAS
----------------------
Ils ne cliquent pas, ne remplissent pas de formulaire, ne s'authentifient pas.
Un site derrière un identifiant reste le domaine des outils de session, ou de
l'extension Chrome. Écarté sciemment : l'authentification non surveillée dans
une tâche planifiée demande un magasin d'identifiants, ce qui est un autre
chantier avec ses propres questions de sûreté.
"""
from __future__ import annotations

import base64
import difflib
import json
import logging
import os
import re
import uuid
from typing import Any

from langchain_core.tools import tool

from app.services.external_content import MARQUEUR, etiquette_externe, wrap_external

logger = logging.getLogger(__name__)

# Là où vivent les pièces jointes, comme `browser_screenshot` (2026-05-06).
# /tmp est éphémère et purgé au redémarrage du conteneur : ces fichiers sont
# des livrables de passage, pas des archives.
_ATTACH_DIR = "/tmp/ely-attachments"

# Une page qui ne se charge pas en 30 s ne se chargera pas. Le budget vaut
# pour la navigation ET pour l'action qui suit.
_NAV_TIMEOUT_MS = 30_000

# Plafond du texte rendu au modèle. `browser_get_text` tronque à 5 000 ; on
# est plus généreux ici parce que l'extraction « un coup » sert souvent à
# lire un article entier, mais on borne quand même : un tour à 200 000
# caractères coûte plus cher que ce qu'il rapporte.
_MAX_TEXT_CHARS = 20_000

# Comparaison : au-delà, le diff lui-même devient illisible pour un modèle.
_MAX_DIFF_LINES = 200


def _erreur(message: str, url: str = "") -> str:
    """Une erreur d'outil rendue au modèle, en JSON comme les succès.

    ⚠️ Rendre une chaîne de prose ici ferait raconter au modèle ce qu'il croit
    avoir compris. Un JSON avec ``ok: false`` se lit sans interprétation.
    """
    return json.dumps(
        {"ok": False, "error": message, "url": url}, ensure_ascii=False,
    )


def _valider_url(url: str) -> str | None:
    """Rend un message d'erreur si l'URL n'est pas utilisable, sinon ``None``.

    ⚠️ On refuse tout ce qui n'est pas http(s). ``file://`` laisserait le
    modèle lire le système de fichiers du conteneur par un outil qui annonce
    « web », et ``javascript:`` n'a rien à faire ici. Le refus est explicite
    plutôt que silencieux : un outil qui rend « rien » sur une entrée mal
    formée fait conclure au modèle que la page est vide.
    """
    u = (url or "").strip()
    if not u:
        return "URL manquante."
    if not re.match(r"^https?://", u, re.I):
        return (
            f"URL refusée : « {u[:80]} ». Seuls http:// et https:// sont "
            f"acceptés — cet outil lit le web, pas le disque."
        )
    # ⚠️ SSRF (audit du 02/09/2026). Le schéma ne suffit pas : ces outils
    # pilotent un Chromium vers l'URL que le modèle leur donne, et
    # `http://169.254.169.254/` (métadonnées cloud), `http://qdrant:6333`
    # (la base vectorielle du réseau Docker) ou `http://127.0.0.1:8000` (le
    # backend lui-même) passaient. Le garde complet existait pour le client
    # MCP — boucle locale, lien local, adresses privées, CGNAT, formes
    # obfusquées — et n'était branché que là. Le web, lui, reste en http.
    from app.services.mcp_egress import MCPEgressBlocked, validate_egress_url
    try:
        validate_egress_url(u, require_https=False)
    except MCPEgressBlocked as exc:
        return (
            f"URL refusée : « {u[:80]} » vise un hôte interne ({exc}). "
            f"Cet outil lit le web public, pas le réseau de la machine."
        )
    return None


async def _charger(page: Any, url: str) -> None:
    """Navigue et attend que le réseau se calme.

    ``domcontentloaded`` puis ``networkidle`` : le premier garantit un DOM, le
    second laisse le temps aux pages qui peignent en JavaScript. L'attente du
    calme est BORNÉE et son échec est ignoré — beaucoup de sites gardent une
    connexion ouverte (télémétrie, websocket) et n'atteignent jamais l'état
    « idle ». Échouer là-dessus rendrait l'outil inutilisable sur la moitié du
    web alors que la page est parfaitement lisible.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:  # noqa: BLE001 — cf. docstring : l'idle est un confort
        logger.debug("web_tool: pas d'état networkidle sur %s — on continue", url)


def _ecrire_piece_jointe(donnees: bytes, extension: str) -> tuple[str, str]:
    """Écrit un livrable et rend ``(chemin, identifiant)``. ``("", "")`` si échec.

    Même dossier et même forme que `browser_screenshot`, pour que les outils
    de livraison (`gmail_send_with_local_attachment`, `drive_upload_local_file`)
    puissent chaîner dessus sans savoir d'où le fichier vient.
    """
    try:
        os.makedirs(_ATTACH_DIR, mode=0o700, exist_ok=True)
        identifiant = uuid.uuid4().hex[:12]
        chemin = f"{_ATTACH_DIR}/{extension}-{identifiant}.{extension}"
        with open(chemin, "wb") as f:
            f.write(donnees)
        return chemin, identifiant
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_tool: écriture de la pièce jointe impossible (%s)", exc)
        return "", ""


def _suite(chemin: str) -> str:
    """Le mode d'emploi de livraison, dans le résultat de l'outil.

    ⚠️ Il est répété dans le RÉSULTAT et pas seulement dans la docstring :
    les petits modèles lisent le tool result bien plus fidèlement que la
    documentation de l'outil. `browser_screenshot` a mesuré le 06/05 que
    l'inclure divise par cinq les « je te l'envoie » sans appel d'outil.
    """
    return (
        f"Fichier prêt. Pour le livrer, applique l'UNE de ces actions — "
        f"l'annoncer en prose ne le livre PAS :\n"
        f"  • Afficher dans le chat → ajoute la ligne « MEDIA:{chemin} » à ta réponse\n"
        f"  • Par mail → gmail_send_with_local_attachment(local_path='{chemin}', …)\n"
        f"  • Sur Drive → drive_upload_local_file(local_path='{chemin}', …)"
    )


# ──────────────────────────────────────────────────────────────────────────
# 1 — Capture
# ──────────────────────────────────────────────────────────────────────────

@tool
async def web_screenshot(
    url: str,
    full_page: bool = True,
    width: int = 1280,
    height: int = 900,
) -> str:
    """Screenshot any URL in one call, with no open browser session.

    USE THIS for scheduled tasks, monitoring, or any «capture this page» request
    where you are not already browsing. It opens the URL in a throwaway context
    and closes it — it never touches the user's current browsing session.
    Use `browser_screenshot` INSTEAD when you are already navigating a site with
    `browser_navigate` and want the page you are currently looking at.

    Args:
        url: Full URL, http:// or https:// only.
        full_page: Capture the entire scrollable page (default) or just the viewport.
        width: Viewport width in pixels (default 1280).
        height: Viewport height in pixels (default 900).
    """
    if (probleme := _valider_url(url)):
        return _erreur(probleme, url)

    from app.services.browser_manager import get_browser_manager

    try:
        async with get_browser_manager().one_shot_page(width, height) as page:
            await _charger(page, url)
            titre = await page.title()
            png = await page.screenshot(full_page=full_page)
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_screenshot: %s — %s", url, exc)
        return _erreur(f"Capture impossible : {exc}", url)

    chemin, identifiant = _ecrire_piece_jointe(png, "png")
    return json.dumps({
        "ok": True,
        "url": url,
        "title": etiquette_externe(titre),
        "local_path": chemin,
        "attachment_id": identifiant,
        "bytes": len(png),
        # Le base64 permet l'affichage inline sans passer par le disque, comme
        # `browser_screenshot`. Tronqué au-delà de 4 Mo : au-delà, il ferait
        # exploser le contexte du modèle pour un gain nul.
        "data": base64.b64encode(png).decode() if len(png) < 4_000_000 else "",
        "mime": "image/png",
        "next_steps": _suite(chemin) if chemin else "",
    }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────
# 2 — PDF
# ──────────────────────────────────────────────────────────────────────────

@tool
async def web_to_pdf(
    url: str,
    landscape: bool = False,
    format: str = "A4",
) -> str:
    """Save any URL as a PDF file, in one call, with no open browser session.

    USE THIS to archive a page, attach it to an email, or keep a dated record —
    typically from a scheduled task. The PDF keeps the page layout, unlike
    `web_extract` which returns plain text.

    Args:
        url: Full URL, http:// or https:// only.
        landscape: Landscape orientation instead of portrait.
        format: Paper format — A4, Letter, Legal, A3.
    """
    if (probleme := _valider_url(url)):
        return _erreur(probleme, url)

    from app.services.browser_manager import get_browser_manager

    try:
        async with get_browser_manager().one_shot_page() as page:
            await _charger(page, url)
            titre = await page.title()
            # ⚠️ `Page.pdf()` n'existe QUE sur Chromium headless. Le dépôt
            # lance Chromium en headless (browser_manager), donc c'est bon —
            # mais si quelqu'un passe un jour en headed pour déboguer, cet
            # appel lèvera, et le message ci-dessous le dira au lieu de
            # laisser un « Erreur : … » opaque.
            pdf = await page.pdf(
                format=format,
                landscape=landscape,
                print_background=True,
            )
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        if "headless" in detail.lower():
            detail = (
                "l'export PDF exige Chromium en mode headless "
                "(browser_manager le lance ainsi — vérifier _LAUNCH_ARGS)"
            )
        logger.warning("web_to_pdf: %s — %s", url, exc)
        return _erreur(f"Export PDF impossible : {detail}", url)

    chemin, identifiant = _ecrire_piece_jointe(pdf, "pdf")
    return json.dumps({
        "ok": True,
        "url": url,
        "title": etiquette_externe(titre),
        "local_path": chemin,
        "attachment_id": identifiant,
        "bytes": len(pdf),
        "next_steps": _suite(chemin) if chemin else "",
    }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────
# 3 — Extraction
# ──────────────────────────────────────────────────────────────────────────

@tool
async def web_extract(
    url: str,
    selector: str = "body",
) -> str:
    """Read the visible text of any URL in one call, with no open browser session.

    USE THIS when you need the CONTENT of a page you are not already browsing —
    an article, a price, a table. Unlike `web_search`, it reads one page you
    already know the address of. Unlike `browser_get_text`, it takes the URL
    itself and needs no prior navigation.

    Returns the text, never a summary — summarising is your job, not the tool's.

    Args:
        url: Full URL, http:// or https:// only.
        selector: CSS selector to narrow the extraction (e.g. 'article', '.price',
            'table', '#content'). Defaults to the whole body.
    """
    if (probleme := _valider_url(url)):
        return _erreur(probleme, url)

    from app.services.browser_manager import get_browser_manager

    try:
        async with get_browser_manager().one_shot_page() as page:
            await _charger(page, url)
            titre = await page.title()
            element = await page.query_selector(selector)
            if element is None:
                # ⚠️ Message ACTIONNABLE, pas « élément introuvable ». Sans le
                # rappel du sélecteur par défaut, le modèle réessaie avec des
                # variantes du même sélecteur au lieu d'élargir.
                return _erreur(
                    f"Aucun élément ne correspond à « {selector} » sur cette page. "
                    f"Réessaie avec selector='body' pour tout lire, ou vérifie "
                    f"le sélecteur.",
                    url,
                )
            texte = (await element.inner_text()) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_extract: %s — %s", url, exc)
        return _erreur(f"Lecture impossible : {exc}", url)

    complet = len(texte) <= _MAX_TEXT_CHARS
    return json.dumps({
        "ok": True,
        "url": url,
        "title": etiquette_externe(titre),
        "selector": selector,
        # ⚠️ CE QUE ÇA CORRIGE (audit du 02/09/2026) : le texte d'une page est
        # du contenu TIERS, la surface d'injection de prompt la plus banale du
        # lot. Seul ce champ est encadré : l'URL demandée, le compteur et la
        # note de troncature sont dits par Ely, les encadrer les rendrait
        # suspects au modèle. Le TITRE, lui, est écrit par la PAGE : il reste
        # hors du cadre (c'est un repère) mais passe par le même traitement
        # que l'origine — relecture du 02/09, il en sortait brut.
        "text": wrap_external(texte[:_MAX_TEXT_CHARS], source="page web", origin=url),
        "chars": len(texte),
        # ⚠️ La troncature s'ANNONCE. Muette, elle ferait conclure au modèle
        # qu'il a lu la page entière, et résumer un article sur sa première
        # moitié en croyant l'avoir lu est exactement le genre d'erreur
        # qu'aucune relecture ne rattrape.
        "truncated": not complet,
        "note": "" if complet else (
            f"Texte tronqué à {_MAX_TEXT_CHARS} caractères sur {len(texte)}. "
            f"Utilise un `selector` plus précis pour cibler ce qui t'intéresse."
        ),
    }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────
# 4 — Comparaison
# ──────────────────────────────────────────────────────────────────────────

@tool
async def web_compare(
    url: str,
    reference_text: str,
    selector: str = "body",
) -> str:
    """Check whether a page changed since you last read it.

    USE THIS for monitoring — a price, a job listing, a status page, a
    changelog. Pass the text you captured last time as `reference_text`; the
    tool re-reads the page and returns what changed, line by line.

    Get `reference_text` from a previous `web_extract` call on the same URL and
    selector. Comparing different selectors returns noise, not a change.

    Args:
        url: Full URL, http:// or https:// only.
        reference_text: The previously captured text to compare against.
        selector: Same CSS selector used for the reference capture.
    """
    if (probleme := _valider_url(url)):
        return _erreur(probleme, url)
    if not (reference_text or "").strip():
        return _erreur(
            "reference_text est vide — il n'y a rien à comparer. Appelle "
            "d'abord web_extract sur cette URL et garde son texte.",
            url,
        )

    from app.services.browser_manager import get_browser_manager

    try:
        async with get_browser_manager().one_shot_page() as page:
            await _charger(page, url)
            titre = await page.title()
            element = await page.query_selector(selector)
            if element is None:
                return _erreur(
                    f"Aucun élément ne correspond à « {selector} » — la page a "
                    f"peut-être changé de structure, ce qui EST un changement.",
                    url,
                )
            actuel = (await element.inner_text()) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_compare: %s — %s", url, exc)
        return _erreur(f"Comparaison impossible : {exc}", url)

    # ⚠️ La référence est le `text` d'un `web_extract` précédent — donc déjà
    # encadré (audit du 02/09/2026). Les deux lignes de cadre porteraient
    # sinon comme des différences, et TOUTE page serait « changée » à chaque
    # tour de veille : le bruit qui fait couper la surveillance au bout de
    # trois jours. Le cadre n'ajoute que ces deux lignes, toutes deux
    # marquées : c'est ce qui rend le filtre exact.
    avant = [ligne for ligne in reference_text.splitlines() if MARQUEUR not in ligne]
    apres = actuel.splitlines()
    diff = [
        ligne for ligne in difflib.unified_diff(
            avant, apres, lineterm="", n=1,
            fromfile="référence", tofile="maintenant",
        )
    ]
    # Les trois premières lignes d'un diff unifié sont des en-têtes : les
    # compter comme des changements ferait dire « modifié » à une page
    # identique.
    corps = [l for l in diff if l[:1] in {"+", "-"} and not l.startswith(("+++", "---"))]
    change = bool(corps)

    return json.dumps({
        "ok": True,
        "url": url,
        "title": etiquette_externe(titre),
        "selector": selector,
        "changed": change,
        "added_lines": sum(1 for l in corps if l.startswith("+")),
        "removed_lines": sum(1 for l in corps if l.startswith("-")),
        "diff": wrap_external(
            "\n".join(diff[:_MAX_DIFF_LINES]), source="page web (différences)",
            origin=url,
        ),
        "diff_truncated": len(diff) > _MAX_DIFF_LINES,
        # Le texte courant est rendu pour servir de référence au PROCHAIN
        # appel. Sans lui, surveiller une page demanderait deux outils à
        # chaque tour, et la référence dériverait d'un tour sur l'autre.
        "current_text": wrap_external(
            actuel[:_MAX_TEXT_CHARS], source="page web", origin=url,
        ),
        "current_truncated": len(actuel) > _MAX_TEXT_CHARS,
    }, ensure_ascii=False)
