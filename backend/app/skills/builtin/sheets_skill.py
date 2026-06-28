# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/sheets_skill.py
# @brief      Sheets Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
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
    domains=[Domain.WORKSPACE],
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
