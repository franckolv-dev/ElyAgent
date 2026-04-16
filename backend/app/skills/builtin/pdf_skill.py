# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/pdf_skill.py
# @brief      PDF reading skill.
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
"""PDF reading skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.pdf_tool import pdf_read, pdf_info

get_skill_registry().register(Skill(
    name="pdf",
    display_name="Lecture PDF",
    description="Lire, extraire le texte et les métadonnées de fichiers PDF (chemin local ou URL)",
    icon="📄",
    scopes=[],
    tools=[pdf_read, pdf_info],
))
