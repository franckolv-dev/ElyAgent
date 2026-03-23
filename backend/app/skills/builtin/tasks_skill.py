from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.tasks_tool import tasks_list, tasks_create, tasks_complete

get_skill_registry().register(Skill(
    name="google_tasks",
    display_name="Google Tasks",
    description="Consulter, créer et compléter des tâches dans Google Tasks",
    icon="✅",
    scopes=["google_oauth"],
    tools=[tasks_list, tasks_create, tasks_complete],
))
