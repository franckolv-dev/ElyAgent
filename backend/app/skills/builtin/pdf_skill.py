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
"""PDF reading skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.pdf_tool import pdf_read, pdf_info

get_skill_registry().register(Skill(
    name="pdf",
    display_name="Lecture PDF",
    description="Lire, extraire le texte et les métadonnées de fichiers PDF (chemin local ou URL)",
    icon="📄",
    scopes=[],
    tools=[pdf_read, pdf_info],
))
