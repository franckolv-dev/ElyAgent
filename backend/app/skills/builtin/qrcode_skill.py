"""QR Code skill — generate QR codes for URLs, Wi-Fi, vCards, etc."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.qrcode_tool import (
    qrcode_generate,
    qrcode_generate_wifi,
    qrcode_generate_vcard,
)

get_skill_registry().register(Skill(
    name="qrcode",
    display_name="QR Code",
    description=(
        "Génère des QR codes pour URLs, textes, Wi-Fi (scan pour se connecter), "
        "et vCards (scan pour ajouter un contact)."
    ),
    icon="◼",
    scopes=[],
    tools=[
        qrcode_generate,
        qrcode_generate_wifi,
        qrcode_generate_vcard,
    ],
))
