# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/browser_manager.py
# @brief      Playwright browser manager for ELY agent
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Playwright browser manager for ELY agent.

Architecture
------------
- One shared Chromium browser instance (headless).
- One isolated BrowserContext per user_id — no shared cookies, storage or
  cache between users or with the host's real browser profile.
- Pages are reused within a session; calling ``get_page()`` for the same
  user always returns the same page object (the most recently active one).

Lifecycle
---------
``start()`` is called once at application startup via ``main.py``.
``stop()`` is called at shutdown.  Both are no-ops if Playwright is
unavailable (graceful degradation).

Sandbox settings
----------------
- ``--no-sandbox`` + ``--disable-setuid-sandbox`` : required inside Docker
- ``--disable-dev-shm-usage`` : prevents crashes on low /dev/shm
- ``--disable-blink-features=AutomationControlled`` : reduces bot detection
- No extensions, no GPU, no notifications
- viewport 1280×720, realistic user-agent
"""
from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-notifications",
    "--disable-blink-features=AutomationControlled",
    "--mute-audio",
]

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class _Session:
    context: object   # playwright BrowserContext
    page: object      # playwright Page
    last_used: float = 0.0  # time.monotonic() du dernier get_page (B-17)


class BrowserManager:
    """Manages a single shared Playwright browser and per-user contexts."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._sessions: dict[str, _Session] = {}
        self._available = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Launch the browser.  Logs a warning if Playwright is not installed."""
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=_LAUNCH_ARGS,
            )
            self._available = True
            logger.info("Playwright Chromium browser ready")
        except Exception as exc:
            logger.warning(
                "Playwright unavailable — browser tools disabled. "
                "Run: playwright install chromium\n  Reason: %s", exc
            )

    async def stop(self) -> None:
        """Close all sessions and the browser."""
        for session in list(self._sessions.values()):
            with suppress(Exception):
                await session.context.close()
        self._sessions.clear()
        if self._browser:
            with suppress(Exception):
                await self._browser.close()
        if self._pw:
            with suppress(Exception):
                await self._pw.stop()
        self._available = False

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        return self._available and self._browser is not None

    async def get_page(self, user_id: str):
        """Return the active page for *user_id*, creating a new session if needed."""
        if not self.is_available():
            raise RuntimeError(
                "Playwright non disponible. "
                "Lance : playwright install chromium  puis redémarre le backend."
            )

        if user_id not in self._sessions:
            try:
                context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=_USER_AGENT,
                    java_script_enabled=True,
                    ignore_https_errors=False,
                    # Completely isolated storage — no host cookies, no local storage
                    storage_state=None,
                )
            except Exception as exc:
                # B-17 (revue 2026-06-10) — Chromium peut crasher alors que
                # is_available() reste vrai : sans relance, le browsing
                # restait cassé pour TOUS les users jusqu'au restart
                # backend. Une relance, puis on retente une fois.
                logger.warning(
                    "new_context a échoué (%s) — relance de Chromium", exc,
                )
                await self.stop()
                await self.start()
                if not self.is_available():
                    raise RuntimeError("Chromium n'a pas pu être relancé") from exc
                context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=_USER_AGENT,
                    java_script_enabled=True,
                    ignore_https_errors=False,
                    storage_state=None,
                )
            page = await context.new_page()
            self._sessions[user_id] = _Session(context=context, page=page)
            logger.debug("New browser session for user %s", user_id)

        session = self._sessions[user_id]
        import time as _time
        session.last_used = _time.monotonic()
        # Reopen page if it was closed
        if session.page.is_closed():
            session.page = await session.context.new_page()
        return session.page

    @asynccontextmanager
    async def one_shot_page(self, viewport_width: int = 1280,
                           viewport_height: int = 900):
        """Une page JETABLE, hors de toute session utilisateur.

        **Pourquoi elle n'est pas ``get_page`` (22/08).** Les outils de session
        agissent sur la page COURANTE d'un utilisateur : ils supposent un
        ``browser_navigate`` préalable, et ils laissent la page où ils l'ont
        mise. C'est ce qu'il faut pour l'exploration interactive.

        Une tâche planifiée n'a rien de tout ça. Elle tourne sans personne,
        parfois pendant que l'utilisateur navigue lui-même — réutiliser sa
        session la lui déplacerait sous les yeux, et le résultat de la tâche
        dépendrait de l'endroit où il l'a laissée. Deux façons de se tromper
        pour le prix d'une.

        Le contexte est créé, utilisé, fermé. Il ne partage ni cookies ni
        stockage avec la session de qui que ce soit — ``storage_state=None``,
        comme les sessions, mais sans la persistance.

        ⚠️ Le NAVIGATEUR reste partagé : lancer un Chromium par appel coûterait
        une seconde et des centaines de Mo. C'est le CONTEXTE qui isole.
        """
        if not self.is_available():
            raise RuntimeError(
                "Playwright non disponible. "
                "Lance : playwright install chromium  puis redémarre le backend."
            )

        context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=_USER_AGENT,
            java_script_enabled=True,
            ignore_https_errors=False,
            storage_state=None,
        )
        try:
            page = await context.new_page()
            yield page
        finally:
            # Fermé quoi qu'il arrive : un contexte oublié garde un process
            # Chromium enfant vivant, et une tâche horaire en fuirait un par
            # heure jusqu'à saturer la limite mémoire du conteneur.
            with suppress(Exception):
                await context.close()

    async def close_session(self, user_id: str) -> None:
        """Explicitly close the browser session for a user."""
        session = self._sessions.pop(user_id, None)
        if session:
            with suppress(Exception):
                await session.context.close()
            logger.debug("Browser session closed for user %s", user_id)

    async def cleanup_idle_sessions(self, max_idle_seconds: float = 900.0) -> int:
        """B-17 (revue 2026-06-10) — évince les contextes inactifs.

        Chaque user qui touchait un tool ``browser_*`` gardait un
        BrowserContext Chromium résident À VIE (RAM par contexte, ×N
        users sur un Mac 32 Go). Appelé par un cron (main.py) toutes les
        10 min ; 15 min d'inactivité par défaut. Retourne le nombre de
        sessions fermées.
        """
        import time as _time

        now = _time.monotonic()
        idle = [
            uid for uid, s in self._sessions.items()
            if now - (s.last_used or 0.0) > max_idle_seconds
        ]
        for uid in idle:
            await self.close_session(uid)
        if idle:
            logger.info("Browser: %d session(s) inactives fermées", len(idle))
        return len(idle)

    def session_count(self) -> int:
        return len(self._sessions)

    # ------------------------------------------------------------------ #
    # Utilities                                                            #
    # ------------------------------------------------------------------ #

    async def screenshot_path(self, user_id: str) -> str:
        """Take a screenshot and return the saved file path.

        Each call produces a uniquely-named file (timestamp suffix) so that
        screenshots from different moments are never overwritten.
        """
        import time as _time
        page = await self.get_page(user_id)
        ts = int(_time.time())
        path = os.path.join(tempfile.gettempdir(), f"ely_browser_{user_id}_{ts}.png")
        await page.screenshot(path=path, full_page=False)
        return path


@lru_cache(maxsize=1)
def get_browser_manager() -> BrowserManager:
    return BrowserManager()
