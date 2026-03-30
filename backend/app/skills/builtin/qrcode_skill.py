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
