# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/docs_skill.py
# @brief      Docs Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.docs_tool import (
    docs_create_document,
    docs_read_document,
    docs_append_text,
    docs_replace_text,
    docs_insert_table,
    docs_batch_update,
    docs_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_docs",
    display_name="Google Docs",
    description=(
        "Créer, lire et modifier des documents Google Docs. "
        "Styles, titres, listes, images, sauts de page — accès complet via "
        "docs_batch_update et docs_raw_api_call."
    ),
    icon="📝",
    scopes=["google_oauth"],
    domains=[Domain.WORKSPACE],
    tools=[
        docs_create_document,
        docs_read_document,
        docs_append_text,
        docs_replace_text,
        docs_insert_table,
        docs_batch_update,
        docs_raw_api_call,
    ],
))
