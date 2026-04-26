# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/contacts_skill.py
# @brief      Google Contacts skill.
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
"""Google Contacts skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.contacts_tool import (
    contacts_search,
    contacts_list,
    contacts_create,
    contacts_get,
    contacts_update,
    contacts_delete,
    contacts_batch_operations,
    contacts_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_contacts",
    display_name="Contacts Google",
    description=(
        "Rechercher, lister, créer, modifier et supprimer des contacts Google. "
        "Opérations en lot (200/appel), groupes, annuaire d'entreprise — "
        "accès complet via contacts_raw_api_call."
    ),
    icon="👤",
    scopes=["google_oauth"],
    tools=[
        contacts_search,
        contacts_list,
        contacts_create,
        contacts_get,
        contacts_update,
        contacts_delete,
        contacts_batch_operations,
        contacts_raw_api_call,
    ],
))
