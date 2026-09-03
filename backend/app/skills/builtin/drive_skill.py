# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/drive_skill.py
# @brief      Drive Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.drive_tool import (
    drive_list_files,
    drive_read_file,
    drive_create_folder,
    drive_create_file,
    drive_update_file,
    drive_upload_local_file,
    drive_move_file,
    drive_rename_file,
    drive_delete_file,
    drive_share_file,
    drive_copy_file,
    drive_export_file,
    drive_find_duplicates,
    drive_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_drive",
    display_name="Google Drive",
    description=(
        "Lister, lire, créer, modifier et organiser des fichiers Drive. "
        "Téléverser un fichier local/binaire (ex. capture d'écran PNG) via "
        "drive_upload_local_file. Partage (permissions), copie, export PDF/Docx, "
        "plus accès complet via drive_raw_api_call."
    ),
    icon="📁",
    scopes=["google_oauth"],
    domains=[Domain.WORKSPACE],
    tools=[
        drive_list_files,
        drive_read_file,
        drive_create_folder,
        drive_create_file,
        drive_update_file,
        drive_upload_local_file,
        drive_move_file,
        drive_rename_file,
        drive_delete_file,
        drive_share_file,
        drive_copy_file,
        drive_export_file,
        drive_find_duplicates,
        drive_raw_api_call,
    ],
))
