# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/os_control_skill.py
# @brief      OS Control skill — Interactive Trainer (Vision + Contrôle desktop)
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""OS Control skill — Interactive Trainer (Vision + Contrôle desktop).

Permet à Ély de voir l'écran de l'utilisateur et d'y interagir pour
démontrer des procédures de manière interactive (tuteur OS/logiciel).

Outils
------
os_screenshot        Capture l'écran complet ou une fenêtre
os_mouse_move        Déplace le curseur (HITL obligatoire)
os_click             Clique à une position (HITL obligatoire)
os_type_text         Tape du texte au clavier (HITL obligatoire)
os_get_active_window Retourne le titre et la classe de la fenêtre active

⚠️  Sécurité : os_mouse_move / os_click / os_type_text sont dans
ALWAYS_CRITICAL_TOOLS → validation humaine obligatoire avant exécution.

Prérequis :
  - Backend non-Docker (ou Docker avec accès display)
  - pyautogui + python3-xlib installés sur l'hôte
  - DISPLAY configuré (pour Linux headless : Xvfb ou forwarding SSH)
"""
from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _get_pyautogui():
    """Import pyautogui lazily — raises ImportError with helpful message if absent."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True    # move mouse to corner to abort
        pyautogui.PAUSE = 0.1        # small delay between actions
        return pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui n'est pas installé. Installe-le avec : pip install pyautogui"
        )


# ------------------------------------------------------------------ #
# Tools                                                                #
# ------------------------------------------------------------------ #

@tool
async def os_screenshot(
    window_title: str = "",
) -> str:
    """Capture l'écran complet ou une fenêtre spécifique.

    Retourne une image base64 affichée directement dans le chat.
    Utilise cet outil avant toute action pour voir l'état actuel de l'écran.

    Args:
        window_title: (optionnel) Titre partiel de la fenêtre à capturer.
                      Si vide, capture l'écran complet.
    """
    import base64
    from io import BytesIO

    try:
        pag = _get_pyautogui()
        screenshot = await asyncio.to_thread(pag.screenshot)

        buf = BytesIO()
        # Downscale to 1280px width max to keep response small
        w, h = screenshot.size
        if w > 1280:
            from PIL import Image
            screenshot = screenshot.resize(
                (1280, int(h * 1280 / w)), Image.LANCZOS
            )

        screenshot.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return json.dumps({
            "type": "image",
            "data": b64,
            "mime": "image/png",
            "prompt": f"Capture d'écran — {window_title or 'écran complet'}",
        })

    except ImportError as exc:
        return f"Impossible de capturer l'écran : {exc}"
    except Exception as exc:
        logger.error("os_screenshot error: %s", exc)
        return f"Erreur lors de la capture d'écran : {exc}"


@tool
async def os_mouse_move(
    x: int,
    y: int,
    duration: float = 0.3,
) -> str:
    """Déplace le curseur de la souris à la position (x, y).

    ⚠️ Action HITL — nécessite une validation humaine avant exécution.

    Conseil : utilise os_screenshot avant pour connaître les coordonnées exactes.
    La résolution habituelle est 1920×1080. Déplace FAILSAFE : souris dans le coin
    supérieur gauche pour annuler toutes les actions.

    Args:
        x:        Coordonnée horizontale en pixels
        y:        Coordonnée verticale en pixels
        duration: Durée du mouvement en secondes (default 0.3)
    """
    try:
        pag = _get_pyautogui()
        await asyncio.to_thread(pag.moveTo, x, y, duration=duration)
        return f"Curseur déplacé vers ({x}, {y})."
    except Exception as exc:
        return f"Erreur lors du déplacement du curseur : {exc}"


@tool
async def os_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """Clique à la position (x, y) avec le bouton spécifié.

    ⚠️ Action HITL — nécessite une validation humaine avant exécution.

    Utilise os_screenshot pour identifier les coordonnées cibles avant de cliquer.

    Args:
        x:       Coordonnée horizontale
        y:       Coordonnée verticale
        button:  'left', 'right' ou 'middle' (default 'left')
        clicks:  Nombre de clics (1 = simple, 2 = double)
    """
    try:
        pag = _get_pyautogui()
        await asyncio.to_thread(pag.click, x, y, button=button, clicks=clicks)
        return f"Clic {button} effectué en ({x}, {y}) — {clicks} fois."
    except Exception as exc:
        return f"Erreur lors du clic : {exc}"


@tool
async def os_type_text(
    text: str,
    interval: float = 0.02,
) -> str:
    """Tape du texte au clavier à la position du curseur actuel.

    ⚠️ Action HITL — nécessite une validation humaine avant exécution.

    Assure-toi que la fenêtre cible est active avant d'appeler cet outil.
    Pour les combinaisons de touches (Ctrl+C, etc.) utilise des raccourcis
    décrits dans le texte sous forme naturelle (l'outil les interprétera).

    Args:
        text:     Texte à taper (supporte les caractères unicode)
        interval: Délai entre chaque frappe en secondes (default 0.02)
    """
    try:
        pag = _get_pyautogui()
        await asyncio.to_thread(pag.typewrite, text, interval=interval)
        return f"Texte tapé : {text!r}"
    except Exception as exc:
        return f"Erreur lors de la saisie clavier : {exc}"


@tool
async def os_hotkey(*keys: str) -> str:
    """Exécute une combinaison de touches clavier (raccourci).

    ⚠️ Action HITL — nécessite une validation humaine avant exécution.

    Exemples : os_hotkey('ctrl', 'c') pour Copier,
               os_hotkey('ctrl', 'z') pour Annuler,
               os_hotkey('alt', 'F4') pour fermer une fenêtre.

    Args:
        keys: Touches à presser simultanément (ex: 'ctrl', 's')
    """
    try:
        pag = _get_pyautogui()
        await asyncio.to_thread(pag.hotkey, *keys)
        return f"Raccourci exécuté : {' + '.join(keys)}"
    except Exception as exc:
        return f"Erreur raccourci clavier : {exc}"


@tool
async def os_get_active_window() -> str:
    """Retourne le titre et les informations de la fenêtre active.

    Utile pour vérifier sur quelle application l'utilisateur est avant d'agir.
    """
    try:
        import subprocess
        result = await asyncio.to_thread(
            subprocess.run,
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=3,
        )
        title = result.stdout.strip()
        return f"Fenêtre active : {title}" if title else "Impossible de détecter la fenêtre active."
    except FileNotFoundError:
        return "xdotool non installé (sudo apt install xdotool)."
    except Exception as exc:
        return f"Erreur : {exc}"


# ------------------------------------------------------------------ #
# Register in HITL always-critical tools                               #
# ------------------------------------------------------------------ #

# Enregistrement dans ALWAYS_CRITICAL_TOOLS pour HITL systématique
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS as _hitl_set

# ALWAYS_CRITICAL_TOOLS est un frozenset — on crée un nouveau set enrichi
# et on remplace la référence globale dans le module security_filter
import app.services.security_filter as _sf_module
_sf_module.ALWAYS_CRITICAL_TOOLS = frozenset(_hitl_set | {
    "os_mouse_move",
    "os_click",
    "os_type_text",
    "os_hotkey",
})


# ------------------------------------------------------------------ #
# Skill registration                                                   #
# ------------------------------------------------------------------ #

get_skill_registry().register(Skill(
    name="os-control",
    display_name="Contrôle OS (Interactive Trainer)",
    description=(
        "Permet à Ély de voir l'écran et de contrôler la souris/clavier pour "
        "des démonstrations interactives. Toutes les actions nécessitent une "
        "validation humaine (HITL). Nécessite pyautogui installé."
    ),
    icon="🖥️",
    scopes=["local"],
    domains=[Domain.DESKTOP],
    tools=[
        os_screenshot,
        os_mouse_move,
        os_click,
        os_type_text,
        os_hotkey,
        os_get_active_window,
    ],
))
