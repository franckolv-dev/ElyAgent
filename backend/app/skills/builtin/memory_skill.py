# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/memory_skill.py
# @brief      Memory Skill module
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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.memory_tool import save_user_preference, save_constraint

get_skill_registry().register(Skill(
    name="memory_preferences",
    display_name="Préférences & Contraintes",
    description="Sauvegarder les préférences de communication et les contraintes permanentes de l'utilisateur",
    icon="🧠",
    scopes=[],
    tools=[save_user_preference, save_constraint],
    enabled_by_default=True,
))
