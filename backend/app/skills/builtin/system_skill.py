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
from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info

get_skill_registry().register(Skill(
    name="system",
    display_name="Système & SSH",
    description="Exécuter des commandes SSH sur des serveurs distants, analyser des fichiers, obtenir des infos système",
    icon="🖥️",
    scopes=["ssh"],
    tools=[ssh_execute, analyze_file, system_info],
))
