from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.calendar_tool import calendar_list_events, calendar_create_event

get_skill_registry().register(Skill(
    name="google_calendar",
    display_name="Google Calendar",
    description="Consulter et créer des événements dans Google Calendar",
    icon="📅",
    scopes=["google_oauth"],
    tools=[calendar_list_events, calendar_create_event],
))
