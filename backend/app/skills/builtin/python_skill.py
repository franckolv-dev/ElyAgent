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
"""Python sandbox skill."""
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.python_tool import python_execute

get_skill_registry().register(Skill(
    name="python-sandbox",
    display_name="Python Sandbox",
    description="Exécute du code Python pour calculs, analyses de données et scripts",
    icon="🐍",
    scopes=[],
    tools=[python_execute],
))
