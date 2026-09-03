# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/qrcode_skill.py
# @brief      QR Code skill — generate QR codes for URLs, Wi-Fi, vCards, etc.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""QR Code skill — generate QR codes for URLs, Wi-Fi, vCards, etc."""
from app.skills.base import Skill, Domain
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
    domains=[Domain.CREATIVE],
    tools=[
        qrcode_generate,
        qrcode_generate_wifi,
        qrcode_generate_vcard,
    ],
))
