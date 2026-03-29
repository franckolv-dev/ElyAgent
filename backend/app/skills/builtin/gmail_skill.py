from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.gmail_tool import (
    gmail_list_emails,
    gmail_read_email,
    gmail_send_email,
    gmail_list_labels,
    gmail_create_label,
    gmail_move_emails,
    gmail_trash_emails,
    gmail_search_for_cleanup,
)

get_skill_registry().register(Skill(
    name="google_gmail",
    display_name="Gmail",
    description=(
        "Lire, chercher, envoyer et organiser des emails via Gmail. "
        "Peut créer des dossiers (labels), déplacer des emails en masse, "
        "mettre à la corbeille et nettoyer la boîte mail (newsletters, promotions, démarchage)."
    ),
    icon="✉️",
    scopes=["google_oauth"],
    tools=[
        gmail_list_emails,
        gmail_read_email,
        gmail_send_email,
        gmail_list_labels,
        gmail_create_label,
        gmail_move_emails,
        gmail_trash_emails,
        gmail_search_for_cleanup,
    ],
))
