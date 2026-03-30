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
"""Notes / Presse-papier skill — create and manage personal notes."""
from app.skills.base import Skill
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
    tools=[
        notes_create,
        notes_list,
        notes_read,
        notes_update,
        notes_delete,
        notes_search,
    ],
))
