# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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
