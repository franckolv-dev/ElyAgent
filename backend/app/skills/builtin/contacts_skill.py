# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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
