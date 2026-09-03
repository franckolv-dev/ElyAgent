# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/contacts_skill.py
# @brief      Google Contacts skill.
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
"""Google Contacts skill."""
from app.skills.base import Skill, Domain
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
    domains=[Domain.WORKSPACE],
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
