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
from app.agent.tools.drive_tool import (
    drive_list_files,
    drive_read_file,
    drive_create_folder,
    drive_create_file,
    drive_update_file,
    drive_move_file,
    drive_rename_file,
    drive_delete_file,
)

get_skill_registry().register(Skill(
    name="google_drive",
    display_name="Google Drive",
    description="Lister, lire, créer, modifier et organiser des fichiers et dossiers sur Google Drive",
    icon="📁",
    scopes=["google_oauth"],
    tools=[
        drive_list_files,
        drive_read_file,
        drive_create_folder,
        drive_create_file,
        drive_update_file,
        drive_move_file,
        drive_rename_file,
        drive_delete_file,
    ],
))
