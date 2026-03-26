"""WhatsApp skill — send messages via Meta WhatsApp Cloud API."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.whatsapp_tool import (
    whatsapp_send,
    whatsapp_send_template,
)

get_skill_registry().register(Skill(
    name="whatsapp",
    display_name="WhatsApp",
    description=(
        "Envoie des messages WhatsApp à n'importe quel numéro via Meta Cloud API. "
        "Nécessite WHATSAPP_PHONE_NUMBER_ID et WHATSAPP_ACCESS_TOKEN configurés."
    ),
    icon="💬",
    scopes=["internet"],
    tools=[
        whatsapp_send,
        whatsapp_send_template,
    ],
))
