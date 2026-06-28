# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/tasks_skill.py
# @brief      Tasks Skill module
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
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.tasks_tool import (
    tasks_list,
    tasks_create,
    tasks_complete,
    tasks_update,
    tasks_delete,
    tasks_list_tasklists,
    tasks_create_tasklist,
    tasks_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_tasks",
    display_name="Google Tasks",
    description=(
        "Consulter, créer, modifier, compléter et supprimer des tâches Google Tasks. "
        "Gérer plusieurs listes, réordonner, sous-tâches, nettoyer les terminées — "
        "accès complet via tasks_raw_api_call."
    ),
    icon="✅",
    scopes=["google_oauth"],
    domains=[Domain.WORKSPACE],
    tools=[
        tasks_list,
        tasks_create,
        tasks_complete,
        tasks_update,
        tasks_delete,
        tasks_list_tasklists,
        tasks_create_tasklist,
        tasks_raw_api_call,
    ],
))
