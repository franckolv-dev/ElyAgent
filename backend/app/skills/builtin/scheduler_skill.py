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
from app.agent.tools.scheduler_tool import scheduler_list_tasks, scheduler_create_task, scheduler_delete_task

get_skill_registry().register(Skill(
    name="scheduler",
    display_name="Tâches planifiées",
    description="Créer des rappels et tâches récurrentes qui s'exécutent automatiquement (cron)",
    icon="⏰",
    scopes=[],
    tools=[scheduler_list_tasks, scheduler_create_task, scheduler_delete_task],
))
