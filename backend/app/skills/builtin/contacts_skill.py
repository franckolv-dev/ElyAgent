"""Google Contacts skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.contacts_tool import contacts_search, contacts_list, contacts_create

get_skill_registry().register(Skill(
    name="google_contacts",
    display_name="Contacts Google",
    description="Rechercher, lister et créer des contacts Google",
    icon="👤",
    scopes=["google_oauth"],
    tools=[contacts_search, contacts_list, contacts_create],
))
