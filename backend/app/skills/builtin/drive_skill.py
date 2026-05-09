# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/drive_skill.py
# @brief      Drive Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from app.skills.base import Skill, Domain
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
        "Partage (permissions), copie, export PDF/Docx, plus accès complet via "
        "drive_raw_api_call."
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
