# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/sheets_skill.py
# @brief      Sheets Skill module
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.sheets_tool import (
    sheets_create_spreadsheet,
    sheets_read_spreadsheet,
    sheets_append_rows,
    sheets_update_cells,
    sheets_delete_rows,
    sheets_add_sheet,
    sheets_list_sheets,
    sheets_batch_update,
    sheets_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_sheets",
    display_name="Google Sheets",
    description=(
        "Créer, lire et modifier des feuilles de calcul Google Sheets. "
        "Trier, insérer colonnes, fusionner, figer, mise en forme, validation — "
        "accès complet à l'API via sheets_batch_update et sheets_raw_api_call."
    ),
    icon="📊",
    scopes=["google_oauth"],
    tools=[
        sheets_create_spreadsheet,
        sheets_read_spreadsheet,
        sheets_append_rows,
        sheets_update_cells,
        sheets_delete_rows,
        sheets_add_sheet,
        sheets_list_sheets,
        sheets_batch_update,
        sheets_raw_api_call,
    ],
))
