# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/__init__.py
# @brief      Package init for skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
from app.skills.registry import get_skill_registry

__all__ = ["get_skill_registry"]
