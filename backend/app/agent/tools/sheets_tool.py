# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/sheets_tool.py
# @brief      Google Sheets tools for ELY agent — create and edit spreadsheets.
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
"""Google Sheets tools for ELY agent — create and edit spreadsheets."""
from __future__ import annotations

import json
import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

logger = logging.getLogger(__name__)


async def _get_sheets_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("sheets", "v4", credentials=creds)


# ⚠️ LE NOM DU PREMIER ONGLET NE SE DEVINE PAS (incident du 27/08/2026).
#
# `range="Sheet1!A1"` était codé en dur à la création. Sur un compte Google en
# français, le premier onglet s'appelle « Feuille 1 » — l'API répond alors
# HTTP 400 « Unable to parse range: Sheet1!A1 ». Le tableur, lui, EST créé :
# seule l'écriture des valeurs échoue. On laisse donc un tableur VIDE derrière
# soi, et l'appelant qui l'exporte livre un fichier vide.
#
# Mesuré sur la mission « Prospection Print LinkedIn » : deux tentatives, deux
# HTTP 400, puis un export XLSX « réussi » d'un tableur vide déposé sur le
# Drive de l'utilisateur.
#
# Le titre se LIT donc dans la réponse de l'API, et il se QUOTE : « Feuille 1 »
# contient une espace, et `Feuille 1!A1` échoue exactement comme `Sheet1!A1`.
_DEFAULT_TAB_TITLE = "Sheet1"


def _quote_tab(title: str) -> str:
    """Rend un titre d'onglet utilisable dans un range A1.

    La notation A1 exige des apostrophes autour d'un titre qui contient une
    espace ou de la ponctuation, et le doublement des apostrophes internes
    (« Ventes d'été » → ``'Ventes d''été'``). Quoter systématiquement est
    valide pour TOUS les titres — un cas de moins à distinguer.
    """
    return "'" + (title or _DEFAULT_TAB_TITLE).replace("'", "''") + "'"


def _first_tab_title(spreadsheet: dict) -> str:
    """Titre du premier onglet d'une réponse `spreadsheets().create/get`.

    Repli sur ``Sheet1`` si la réponse ne porte pas la liste des onglets :
    c'est l'ancien comportement, et il vaut mieux une écriture qui tente sa
    chance qu'une exception sur une clé absente.
    """
    sheets = (spreadsheet or {}).get("sheets") or []
    if not sheets:
        return _DEFAULT_TAB_TITLE
    return (sheets[0].get("properties") or {}).get("title") or _DEFAULT_TAB_TITLE


async def _resolve_tab(service, spreadsheet_id: str) -> str:
    """Titre du premier onglet d'un tableur existant (best-effort)."""
    try:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return _first_tab_title(meta)
    except Exception as exc:  # noqa: BLE001 — le repli reste utilisable
        logger.debug("Onglet par défaut non résolu (%s) — repli %s",
                     exc, _DEFAULT_TAB_TITLE)
        return _DEFAULT_TAB_TITLE


@tool
async def sheets_create_spreadsheet(
    title: str,
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new Google Sheets spreadsheet (equivalent to an Excel file).

    Args:
        title: Spreadsheet title
        headers: Column headers for the first row (e.g. ["Name", "Date", "Amount"])
        rows: Data rows as list of lists (e.g. [["Alice", "2025-01-01", 100], ["Bob", "2025-01-02", 200]])
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        spreadsheet = service.spreadsheets().create(
            body={"properties": {"title": title}}
        ).execute()
        ss_id = spreadsheet["spreadsheetId"]
        url = f"https://docs.google.com/spreadsheets/d/{ss_id}/edit"

        values: list[list] = []
        if headers:
            values.append(headers)
        if rows:
            values.extend(rows)

        if values:
            service.spreadsheets().values().update(
                spreadsheetId=ss_id,
                range=f"{_quote_tab(_first_tab_title(spreadsheet))}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()

        row_count = len(values)
        return (
            f"Feuille de calcul créée : '{title}'\n"
            f"URL : {url}\n"
            f"ID : {ss_id}\n"
            f"Lignes insérées : {row_count}"
        )
    except Exception as e:
        return f"Erreur création feuille : {e}"


@tool
async def sheets_read_spreadsheet(
    spreadsheet_id: str,
    sheet_range: str | None = None,
    max_rows: int = 100,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read data from a Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID (from the URL or sheets_create_spreadsheet)
        sheet_range: Range to read, e.g. 'Feuille 1!A1:E20'. Omit it to read
            the whole first tab, whatever its name is in the user's locale —
            do NOT pass "Sheet1" as a guess.
        max_rows: Maximum number of rows to return (default 100)
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        # Une plage explicite fait autorité ; sinon on vise le vrai premier
        # onglet — « Sheet1 » n'existe pas sur un compte non anglophone.
        if not sheet_range:
            sheet_range = _quote_tab(await _resolve_tab(service, spreadsheet_id))
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
        ).execute()

        values = result.get("values", [])
        if not values:
            return "Feuille vide ou plage introuvable."

        # Format as readable table
        rows = values[:max_rows]
        lines = []
        for i, row in enumerate(rows):
            lines.append(f"Ligne {i + 1}: {' | '.join(str(cell) for cell in row)}")

        truncated = f"\n... ({len(values) - max_rows} lignes supplémentaires)" if len(values) > max_rows else ""
        return f"{len(rows)} ligne(s) lue(s):\n\n" + "\n".join(lines) + truncated
    except Exception as e:
        return f"Erreur lecture feuille : {e}"


@tool
async def sheets_append_rows(
    spreadsheet_id: str,
    rows: list[list[str]],
    sheet_name: str | None = None,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Append rows to an existing Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        rows: Rows to append as list of lists (e.g. [["Alice", "2025-06-01", 150]])
        sheet_name: Name of the sheet tab. Omit it to target the first tab of
            the spreadsheet, whatever its name is in the user's locale
            ("Feuille 1" in French) — do NOT pass "Sheet1" as a guess.
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        # Un `sheet_name` explicite fait autorité ; sinon on lit le vrai
        # premier onglet plutôt que de parier sur « Sheet1 ».
        sheet_name = sheet_name or await _resolve_tab(service, spreadsheet_id)
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_tab(sheet_name)}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

        updates = result.get("updates", {})
        updated_rows = updates.get("updatedRows", len(rows))
        return f"{updated_rows} ligne(s) ajoutée(s) à la feuille '{sheet_name}' (ID: {spreadsheet_id})"
    except Exception as e:
        return f"Erreur ajout lignes : {e}"


@tool
async def sheets_update_cells(
    spreadsheet_id: str,
    sheet_range: str,
    values: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update specific cells in a Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        sheet_range: Range to update, e.g. 'Sheet1!A1:C3'
        values: JSON string of list of lists, e.g. '[["Name","Age"],["Alice","30"]]'
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        parsed_values = json.loads(values)
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
            valueInputOption="USER_ENTERED",
            body={"values": parsed_values},
        ).execute()

        updated = result.get("updatedCells", 0)
        return f"{updated} cellule(s) mise(s) à jour dans '{sheet_range}' (ID: {spreadsheet_id})"
    except json.JSONDecodeError:
        return "Erreur : le paramètre 'values' doit être un JSON valide (liste de listes)."
    except Exception as e:
        return f"Erreur mise à jour cellules : {e}"


@tool
async def sheets_delete_rows(
    spreadsheet_id: str,
    sheet_id: int,
    start_row: int,
    end_row: int,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Delete rows from a Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        sheet_id: Numeric tab ID (0 for the first sheet)
        start_row: Start row index (0-indexed, inclusive)
        end_row: End row index (0-indexed, exclusive)
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": start_row,
                                "endIndex": end_row,
                            }
                        }
                    }
                ]
            },
        ).execute()

        count = end_row - start_row
        return f"{count} ligne(s) supprimée(s) (lignes {start_row} à {end_row - 1}) (ID: {spreadsheet_id})"
    except Exception as e:
        return f"Erreur suppression lignes : {e}"


@tool
async def sheets_add_sheet(
    spreadsheet_id: str,
    title: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Add a new sheet tab to an existing Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        title: Name of the new sheet tab
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {"title": title}
                        }
                    }
                ]
            },
        ).execute()

        replies = result.get("replies", [{}])
        new_id = replies[0].get("addSheet", {}).get("properties", {}).get("sheetId", "?")
        return f"Onglet '{title}' ajouté (sheetId: {new_id}) (ID: {spreadsheet_id})"
    except Exception as e:
        return f"Erreur ajout onglet : {e}"


@tool
async def sheets_list_sheets(
    spreadsheet_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all sheet tabs in a Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties",
        ).execute()

        sheets = result.get("sheets", [])
        if not sheets:
            return "Aucun onglet trouvé."

        lines = [f"{len(sheets)} onglet(s) :"]
        for s in sheets:
            props = s.get("properties", {})
            lines.append(
                f"• {props.get('title', 'Sans titre')} — "
                f"sheetId: {props.get('sheetId')}, "
                f"index: {props.get('index')}, "
                f"{props.get('gridProperties', {}).get('rowCount', '?')} lignes × "
                f"{props.get('gridProperties', {}).get('columnCount', '?')} colonnes"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Erreur liste onglets : {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Generic batch / raw API tools — unlocks ANY Sheets operation
# ──────────────────────────────────────────────────────────────────────────────

_SHEETS_BATCH_UPDATE_GUIDE = """
Types de requêtes Sheets les plus utiles (à mettre dans la liste `requests`) :

• Trier une plage
  {"sortRange": {
      "range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 100,
                "startColumnIndex": 0, "endColumnIndex": 5},
      "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]}}

• Insérer des lignes ou colonnes
  {"insertDimension": {
      "range": {"sheetId": 0, "dimension": "COLUMNS",
                "startIndex": 2, "endIndex": 3},
      "inheritFromBefore": true}}

• Supprimer des lignes ou colonnes
  {"deleteDimension": {
      "range": {"sheetId": 0, "dimension": "COLUMNS",
                "startIndex": 2, "endIndex": 4}}}

• Fusionner des cellules
  {"mergeCells": {
      "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 3},
      "mergeType": "MERGE_ALL"}}

• Figer lignes/colonnes
  {"updateSheetProperties": {
      "properties": {"sheetId": 0,
                     "gridProperties": {"frozenRowCount": 1}},
      "fields": "gridProperties.frozenRowCount"}}

• Mise en forme — gras, couleur fond, alignement
  {"repeatCell": {
      "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
      "cell": {"userEnteredFormat": {
          "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.8},
          "textFormat": {"bold": true, "foregroundColor":
              {"red": 1, "green": 1, "blue": 1}},
          "horizontalAlignment": "CENTER"}},
      "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}}

• Mise en forme conditionnelle
  {"addConditionalFormatRule": {
      "rule": {"ranges": [{"sheetId": 0}],
               "booleanRule": {"condition": {"type": "NUMBER_GREATER",
                                              "values": [{"userEnteredValue": "100"}]},
                               "format": {"backgroundColor":
                                   {"red": 1, "green": 0.8, "blue": 0.8}}}},
      "index": 0}}

• Ajuster largeur colonne
  {"updateDimensionProperties": {
      "range": {"sheetId": 0, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": 3},
      "properties": {"pixelSize": 150},
      "fields": "pixelSize"}}

• Validation de données (liste déroulante)
  {"setDataValidation": {
      "range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 100,
                "startColumnIndex": 3, "endColumnIndex": 4},
      "rule": {"condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": "Oui"},
                                         {"userEnteredValue": "Non"}]},
               "showCustomUi": true, "strict": true}}}

• Renommer / dupliquer / supprimer un onglet
  {"updateSheetProperties": {"properties": {"sheetId": 0, "title": "Nouveau"},
                              "fields": "title"}}
  {"duplicateSheet": {"sourceSheetId": 0, "newSheetName": "Copie"}}
  {"deleteSheet": {"sheetId": 123}}

• Créer un filtre
  {"setBasicFilter": {
      "filter": {"range": {"sheetId": 0,
                            "startRowIndex": 0, "endRowIndex": 100,
                            "startColumnIndex": 0, "endColumnIndex": 5}}}}

Pour trouver `sheetId` d'un onglet, appeler d'abord `sheets_list_sheets`.
"""


@tool
async def sheets_batch_update(
    spreadsheet_id: str,
    requests_json: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Execute one or more advanced operations on a Google Sheets spreadsheet.

    Gives access to the FULL `spreadsheets.batchUpdate` API: sort ranges,
    insert/delete rows or columns, merge cells, freeze rows, format cells
    (bold, background, alignment, conditional formatting), column width,
    data validation (dropdowns), rename/duplicate/delete tabs, filters, etc.

    Args:
        spreadsheet_id: The spreadsheet ID.
        requests_json: JSON array of Sheets batchUpdate requests.
            Example for sorting by column C descending:
              '[{"sortRange": {"range": {"sheetId": 0, "startRowIndex": 1,
              "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 5},
              "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]}}]'

            Many request types are available — see the prompt guide for
            sort, insert/delete dim, mergeCells, updateSheetProperties,
            repeatCell (formatting), addConditionalFormatRule,
            updateDimensionProperties, setDataValidation, duplicateSheet,
            setBasicFilter, etc.
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        requests = json.loads(requests_json)
    except json.JSONDecodeError as e:
        return f"Erreur : requests_json doit être un JSON valide (tableau de requêtes). Détail : {e}"

    if not isinstance(requests, list):
        return "Erreur : requests_json doit être un tableau JSON."
    if not requests:
        return "Erreur : aucune requête fournie."

    try:
        logger.info(
            "sheets_batch_update: spreadsheet=%s, %d request(s), types=%s",
            spreadsheet_id, len(requests),
            [list(r.keys())[0] if isinstance(r, dict) and r else "?" for r in requests],
        )
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

        replies = result.get("replies", [])
        lines = [f"✓ {len(replies)} opération(s) exécutée(s) sur la feuille {spreadsheet_id}"]

        # Surface useful reply details (new sheet IDs, etc.)
        for i, reply in enumerate(replies):
            if not reply:
                continue
            op = list(reply.keys())[0] if reply else None
            if op == "addSheet":
                props = reply["addSheet"].get("properties", {})
                lines.append(f"  [{i}] addSheet → '{props.get('title')}' sheetId={props.get('sheetId')}")
            elif op == "duplicateSheet":
                props = reply["duplicateSheet"].get("properties", {})
                lines.append(f"  [{i}] duplicateSheet → '{props.get('title')}' sheetId={props.get('sheetId')}")
            elif op:
                lines.append(f"  [{i}] {op}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("sheets_batch_update failed: %s", e)
        return f"Erreur sheets_batch_update : {e}"


sheets_batch_update.description = (sheets_batch_update.description or "") + _SHEETS_BATCH_UPDATE_GUIDE


@tool
async def sheets_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Google Sheets API (v4) directly.

    Escape hatch for advanced operations not covered by the dedicated tools.
    Prefer `sheets_batch_update` for spreadsheet mutations — use this only
    when you need a method not reachable through batchUpdate.

    Args:
        method_path: Dot-separated Sheets API method, e.g.
            'spreadsheets.get', 'spreadsheets.values.batchGet',
            'spreadsheets.values.batchUpdate',
            'spreadsheets.developerMetadata.search'.
        params_json: JSON object of query parameters passed as kwargs.
            Example: '{"spreadsheetId": "abc123", "range": "Sheet1!A1:B10"}'
        body_json: Optional JSON body (for POST/PATCH methods).

    Returns a truncated JSON-serialized response.
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "sheets")
