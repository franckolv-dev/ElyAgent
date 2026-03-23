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
