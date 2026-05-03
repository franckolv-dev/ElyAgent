# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/docs_skill.py
# @brief      Docs Skill module
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
