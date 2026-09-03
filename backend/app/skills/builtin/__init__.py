# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/__init__.py
# @brief      Builtin skill registration
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Builtin skill registration.

Importing this package (or calling ``register_all()``) registers all
built-in skills into the global SkillRegistry.  ``app.main`` does this
once at application startup, before any request is served.

To add a new built-in skill — TWO PATTERNS SUPPORTED
----------------------------------------------------
**Recommended (Sprint 2+)** — decorator-based, single-step:
  1. In your tool file (``app/agent/tools/my_tool.py``) decorate the
     ``@tool``-wrapped callable with ``@register(...)`` from
     ``app.skills.decorator``. That's it. ``auto_discover_tools()``
     called below will scan the package, group tools by ``skill_name``,
     and register the resulting Skill(s) in one shot.

**Legacy (still supported indefinitely)** — manual registration:
  1. Create ``app/skills/builtin/my_skill.py``
  2. At module level, call ``get_skill_registry().register(Skill(...))``
  3. Add an import of your module in the list below.

The two patterns can coexist: if a skill_name is already registered
manually, auto-discovery skips it (legacy wins). This allows progressive
migration without ever shipping a broken state.
"""

import logging

logger = logging.getLogger(__name__)


def register_all() -> None:
    """Import every builtin skill module to trigger side-effect registration."""
    # Existing tools wrapped as skills
    from app.skills.builtin import find_tool_skill   # noqa: F401  (universal — tool discovery)
    from app.skills.builtin import mcp_model_skill   # noqa: F401  (client MCP — flag-gated)
    from app.skills.builtin import system_skill      # noqa: F401
    from app.skills.builtin import gmail_skill       # noqa: F401
    from app.skills.builtin import calendar_skill    # noqa: F401
    from app.skills.builtin import drive_skill       # noqa: F401
    from app.skills.builtin import docs_skill        # noqa: F401
    from app.skills.builtin import sheets_skill      # noqa: F401
    from app.skills.builtin import tasks_skill       # noqa: F401
    from app.skills.builtin import scheduler_skill   # noqa: F401
    # New packaged skills
    from app.skills.builtin import weather_skill     # noqa: F401
    from app.skills.builtin import news_skill        # noqa: F401
    from app.skills.builtin import translate_skill   # noqa: F401
    from app.skills.builtin import browser_skill     # noqa: F401
    from app.skills.builtin import browser_extension_skill  # noqa: F401
    from app.skills.builtin import briefing_skill    # noqa: F401
    from app.skills.builtin import watchdog_skill    # noqa: F401
    from app.skills.builtin import image_skill       # noqa: F401
    from app.skills.builtin import contacts_skill    # noqa: F401
    from app.skills.builtin import python_skill      # noqa: F401
    from app.skills.builtin import pdf_skill         # noqa: F401
    from app.skills.builtin import search_skill      # noqa: F401
    from app.skills.builtin import web_automation_skill  # noqa: F401
    from app.skills.builtin import notes_skill       # noqa: F401
    from app.skills.builtin import maps_skill        # noqa: F401
    from app.skills.builtin import youtube_skill     # noqa: F401
    from app.skills.builtin import qrcode_skill      # noqa: F401
    from app.skills.builtin import telegram_skill    # noqa: F401
    from app.skills.builtin import github_skill      # noqa: F401
    from app.skills.builtin import vision_skill      # noqa: F401
    from app.skills.builtin import os_control_skill    # noqa: F401
    from app.skills.builtin import mcp_generator_skill  # noqa: F401
    from app.skills.builtin import memory_skill          # noqa: F401
    from app.skills.builtin import knowledge_skill       # noqa: F401
    from app.skills.builtin import agentic_rag_skill     # noqa: F401
    from app.skills.builtin import system_diag_skill     # noqa: F401
    from app.skills.builtin import reversible_skill       # noqa: F401  (substrat — annulation)
    from app.skills.builtin.desktop_skill import register_desktop_skill
    register_desktop_skill()
    from app.skills.builtin.trainer_skill import register_trainer_skill
    register_trainer_skill()

    # Sprint 2 — Auto-discovery of @register'd tools. Runs AFTER all the
    # legacy manual registrations above so that legacy skill_names win
    # (the auto-discovery scanner skips any skill_name already in the
    # registry). This lets us migrate tools to the decorator one by one.
    from app.skills.auto_discover import auto_discover_tools
    try:
        n = auto_discover_tools(packages=("app.agent.tools",))
        if n:
            logger.info("Auto-discovered %d decorator-registered skill(s)", n)
    except Exception as exc:  # noqa: BLE001 — never block app startup on this
        logger.warning(
            "auto_discover_tools failed (%s) — falling back to legacy registrations only",
            exc,
        )

    # Descriptions courtes destinées au modèle. EN DERNIER : tout le catalogue
    # doit être enregistré, découverte automatique comprise, sinon une partie
    # des remplacements ne trouverait pas sa cible. Les docstrings des modules
    # ne sont pas touchées — seul l'attribut envoyé au modèle change.
    from app.agent.tool_descriptions import apply_slim_descriptions
    try:
        _slim = apply_slim_descriptions()
        if _slim:
            logger.info("Descriptions courtes appliquées à %d outil(s)", _slim)
    except Exception as exc:  # noqa: BLE001 — un budget de tokens ne doit
        logger.warning("descriptions courtes ignorées (%s)", exc)  # pas bloquer
