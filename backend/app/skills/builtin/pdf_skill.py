# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/pdf_skill.py
# @brief      PDF reading skill.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""PDF reading skill."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.pdf_tool import pdf_read, pdf_info, pdf_to_docx

get_skill_registry().register(Skill(
    name="pdf",
    display_name="Lecture PDF",
    description=(
        "Lire, extraire le texte et les métadonnées de fichiers PDF "
        "(chemin local ou URL), et les convertir en Word .docx"
    ),
    icon="📄",
    scopes=[],
    domains=[Domain.CREATIVE],
    tools=[pdf_read, pdf_info, pdf_to_docx],
))
