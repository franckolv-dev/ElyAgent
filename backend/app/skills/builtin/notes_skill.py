# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/notes_skill.py
# @brief      Notes / Presse-papier skill — create and manage personal notes.
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
"""Notes / Presse-papier skill — create and manage personal notes."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.notes_tool import (
    notes_create,
    notes_list,
    notes_read,
    notes_update,
    notes_delete,
    notes_search,
)

get_skill_registry().register(Skill(
    name="notes",
    display_name="Notes & Presse-papier",
    description=(
        "Crée, consulte, modifie et supprime des notes personnelles / presse-papier. "
        "Supporte titres, contenu, tags et épingles."
    ),
    icon="📝",
    scopes=[],
    domains=[Domain.MEMORY],
    tools=[
        notes_create,
        notes_list,
        notes_read,
        notes_update,
        notes_delete,
        notes_search,
    ],
))
