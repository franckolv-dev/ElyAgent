# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/tasks_skill.py
# @brief      Tasks Skill module
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
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
