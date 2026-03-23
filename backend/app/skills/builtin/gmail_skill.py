from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.gmail_tool import gmail_list_emails, gmail_read_email, gmail_send_email

get_skill_registry().register(Skill(
    name="google_gmail",
    display_name="Gmail",
    description="Lire, chercher et envoyer des emails via Gmail",
    icon="✉️",
    scopes=["google_oauth"],
    tools=[gmail_list_emails, gmail_read_email, gmail_send_email],
))
