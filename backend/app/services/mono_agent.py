# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mono_agent.py
# @brief      Mono-agent mode flag — forces every query through the `general`
#             specialist with all tools bound, bypassing the LLM/keyword router.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Mono-agent mode flag.

Quand activé, l'agent court-circuite tout le routeur (keyword + LLM + sticky)
et envoie chaque message sur le specialist ``general`` qui a accès à tous les
tools. Utile pour valider un nouveau modèle agentique long-contexte (Kimi
K2.6, GPT-5, Claude Sonnet 4.6…) sans subir les erreurs de classification.

Le flag est persisté dans la table ``system_config`` (clé ``mono_agent_mode``,
valeurs ``"true"`` / ``"false"``) et caché en mémoire pour éviter un round-trip
DB à chaque requête.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# In-process cache. Loaded on startup via load_mono_agent_flag().
_enabled: bool = False


def is_mono_agent_enabled() -> bool:
    """Return the current value of the mono-agent flag (cache-backed)."""
    return _enabled


def set_mono_agent_enabled(enabled: bool) -> None:
    """Update the in-memory flag. Persistence to DB is handled by the caller."""
    global _enabled
    _enabled = bool(enabled)
    logger.info("Mono-agent mode → %s", "ENABLED" if _enabled else "disabled")


async def load_mono_agent_flag() -> None:
    """Load the flag from system_config table on startup."""
    from app.services.system_config import get_config
    try:
        raw = await get_config("mono_agent_mode", "")
        set_mono_agent_enabled(raw.lower() in ("true", "1", "yes", "on"))
    except Exception:
        # DB pas prête au boot → on garde le défaut (False).
        # exc_info=True pour conserver la stacktrace dans les logs.
        logger.warning("load_mono_agent_flag failed", exc_info=True)


async def save_mono_agent_flag(enabled: bool) -> None:
    """Persist the flag to DB and refresh the in-memory cache."""
    from app.services.system_config import set_config
    await set_config(
        "mono_agent_mode",
        "true" if enabled else "false",
        is_secret=False,
        description="When true, all queries bypass the router and go to `general`.",
    )
    set_mono_agent_enabled(enabled)
