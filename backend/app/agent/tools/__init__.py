# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/__init__.py
# @brief      Package init for tools
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
