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
