# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/whatsapp_skill.py
# @brief      WhatsApp skill — send messages via Meta WhatsApp Cloud API.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""WhatsApp skill — send messages via Meta WhatsApp Cloud API."""
from app.skills.base import Skill, Domain
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
    domains=[Domain.MEMORY],
    tools=[
        whatsapp_send,
        whatsapp_send_template,
    ],
))
