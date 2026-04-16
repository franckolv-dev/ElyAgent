# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/__init__.py
# @brief      Package init for tools
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
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
# Tools are now managed by the SkillRegistry (app.skills).
# This shim exists for backward-compatibility only.
# New code should use: from app.skills import get_skill_registry

from app.skills.registry import get_skill_registry as _get_registry


def _all_tools():
    """Lazily fetched tool list — always reflects the current registry state."""
    return _get_registry().all_tools


# WARNING: do NOT add a module-level `all_tools = _all_tools()` here.
# register_all() has not been called yet at import time, so the registry
# is empty and the call would always return an empty list.
# Use get_skill_registry().all_tools directly instead.
