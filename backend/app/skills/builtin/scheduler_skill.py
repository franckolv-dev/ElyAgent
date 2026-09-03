# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/scheduler_skill.py
# @brief      Scheduler Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.scheduler_tool import (
    scheduler_list_tasks,
    scheduler_create_task,
    scheduler_delete_task,
    scheduler_update_task,
    scheduler_run_task,
)

get_skill_registry().register(Skill(
    name="scheduler",
    display_name="Tâches planifiées",
    description="Créer des rappels et tâches récurrentes qui s'exécutent automatiquement (cron)",
    icon="⏰",
    scopes=[],
    domains=[Domain.INFRA],
    tools=[
        scheduler_list_tasks,
        scheduler_create_task,
        scheduler_delete_task,
        scheduler_update_task,
        scheduler_run_task,
    ],
))
