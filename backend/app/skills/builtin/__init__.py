# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/__init__.py
# @brief      Builtin skill registration
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
"""Builtin skill registration.

Importing this package (or calling ``register_all()``) registers all
built-in skills into the global SkillRegistry.  ``app.main`` does this
once at application startup, before any request is served.

To add a new built-in skill:
  1. Create ``app/skills/builtin/my_skill.py``
  2. At module level, call ``get_skill_registry().register(Skill(...))``
  3. Add an import of your module in the list below.
"""


def register_all() -> None:
    """Import every builtin skill module to trigger side-effect registration."""
    # Existing tools wrapped as skills
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
    from app.skills.builtin import notes_skill       # noqa: F401
    from app.skills.builtin import maps_skill        # noqa: F401
    from app.skills.builtin import youtube_skill     # noqa: F401
    from app.skills.builtin import qrcode_skill      # noqa: F401
    from app.skills.builtin import whatsapp_skill    # noqa: F401
    from app.skills.builtin import telegram_skill    # noqa: F401
    from app.skills.builtin import vision_skill      # noqa: F401
    from app.skills.builtin import os_control_skill    # noqa: F401
    from app.skills.builtin import mcp_generator_skill  # noqa: F401
    from app.skills.builtin import memory_skill          # noqa: F401
    from app.skills.builtin import knowledge_skill       # noqa: F401
    from app.skills.builtin import agentic_rag_skill     # noqa: F401
    from app.skills.builtin import system_diag_skill     # noqa: F401
    from app.skills.builtin.desktop_skill import register_desktop_skill
    register_desktop_skill()
    from app.skills.builtin.trainer_skill import register_trainer_skill
    register_trainer_skill()
