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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.tasks_tool import (
    tasks_list,
    tasks_create,
    tasks_complete,
    tasks_update,
    tasks_delete,
    tasks_list_tasklists,
    tasks_create_tasklist,
)

get_skill_registry().register(Skill(
    name="google_tasks",
    display_name="Google Tasks",
    description=(
        "Consulter, créer, modifier, compléter et supprimer des tâches Google Tasks. "
        "Gérer plusieurs listes de tâches."
    ),
    icon="✅",
    scopes=["google_oauth"],
    tools=[
        tasks_list,
        tasks_create,
        tasks_complete,
        tasks_update,
        tasks_delete,
        tasks_list_tasklists,
        tasks_create_tasklist,
    ],
))
