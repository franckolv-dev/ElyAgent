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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.memory_tool import save_user_preference, save_constraint

get_skill_registry().register(Skill(
    name="memory_preferences",
    display_name="Préférences & Contraintes",
    description="Sauvegarder les préférences de communication et les contraintes permanentes de l'utilisateur",
    icon="🧠",
    scopes=[],
    tools=[save_user_preference, save_constraint],
    enabled_by_default=True,
))
