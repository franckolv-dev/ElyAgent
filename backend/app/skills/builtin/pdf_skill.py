# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/pdf_skill.py
# @brief      PDF reading skill.
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""PDF reading skill."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.pdf_tool import pdf_read, pdf_info

get_skill_registry().register(Skill(
    name="pdf",
    display_name="Lecture PDF",
    description="Lire, extraire le texte et les métadonnées de fichiers PDF (chemin local ou URL)",
    icon="📄",
    scopes=[],
    domains=[Domain.CREATIVE],
    tools=[pdf_read, pdf_info],
))
