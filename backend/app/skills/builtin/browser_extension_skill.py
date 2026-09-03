# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/browser_extension_skill.py
# @brief      Skill that exposes the ELY browser-extension tools to the agent.
#             These tools let Ely act in the user's REAL Chrome tab
#             (with their cookies, sessions, logged-in pages).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Browser extension skill — acts on the user's actual Chrome tab.

Use cases unlocked by this skill:
  - "Look at my LinkedIn profile and tell me my latest post impressions"
  - "What's in my Gmail inbox right now" (UI-level, not API)
  - "Read this Amazon order page and summarise"
  - "What's the X thread on the active tab saying"

All of these require the user's authenticated session, which only their
real browser has. Server-side Playwright can't do this without leaking
the user's credentials.
"""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.browser_extension_tool import (
    browser_list_tabs,
    browser_open_tab,
    browser_tab_wait_loaded,
    browser_tab_wait_for_selector,
    browser_tab_get_url,
    browser_tab_read_text,
    browser_tab_read_html,
    browser_tab_screenshot,
    browser_tab_click,
    browser_tab_fill,
    browser_tab_navigate,
    browser_close_tab,
    # Sprint 0.7 — inspecteurs Chrome en lecture seule. Définis depuis
    # longtemps dans browser_extension_tool.py et bindés au profil `default`,
    # mais JAMAIS enregistrés ici : l'agent ne les voyait pas et affirmait de
    # bonne foi ne pas pouvoir consulter l'historique. Trouvé par le contrôle
    # de réalité (#265).
    browser_history_search,
    browser_bookmarks_search,
    browser_downloads_search,
)

get_skill_registry().register(Skill(
    name="browser_extension",
    display_name="Onglet Chrome actif (extension)",
    description=(
        "Lit le contenu de l'onglet Chrome actuellement actif chez l'utilisateur, "
        "avec ses vraies sessions et cookies. À UTILISER systématiquement quand "
        "l'utilisateur demande de regarder une page authentifiée (LinkedIn, Gmail, "
        "Amazon, X, Discord, intranet…) plutôt que les outils de navigation "
        "headless serveur (qui n'ont pas la session de l'utilisateur)."
    ),
    icon="🌐",
    scopes=[],
    domains=[Domain.RESEARCH],
    tools=[
        browser_list_tabs,
        browser_open_tab,
        browser_tab_wait_loaded,
        browser_tab_wait_for_selector,
        browser_tab_get_url,
        browser_tab_read_text,
        browser_tab_read_html,
        browser_tab_screenshot,
        browser_tab_click,
        browser_tab_fill,
        browser_tab_navigate,
        browser_close_tab,
        browser_history_search,
        browser_bookmarks_search,
        browser_downloads_search,
    ],
))
