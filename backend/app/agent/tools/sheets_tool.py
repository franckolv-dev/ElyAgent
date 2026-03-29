"""Google Sheets tools for ELY agent — create and edit spreadsheets."""
from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


async def _get_sheets_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("sheets", "v4", credentials=creds)


@tool
async def sheets_create_spreadsheet(
    title: str,
    headers: list[str] | None = None,
    rows: list[list] | None = None,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
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
                range="Sheet1!A1",
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
    sheet_range: str = "Sheet1",
    max_rows: int = 100,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read data from a Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID (from the URL or sheets_create_spreadsheet)
        sheet_range: Range to read, e.g. 'Sheet1', 'Sheet1!A1:E20', 'Feuille 1'
        max_rows: Maximum number of rows to return (default 100)
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
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
    rows: list[list],
    sheet_name: str = "Sheet1",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Append rows to an existing Google Sheets spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        rows: Rows to append as list of lists (e.g. [["Alice", "2025-06-01", 150]])
        sheet_name: Name of the sheet tab (default: Sheet1)
    """
    service = await _get_sheets_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

        updates = result.get("updates", {})
        updated_rows = updates.get("updatedRows", len(rows))
        return f"{updated_rows} ligne(s) ajoutée(s) à la feuille '{sheet_name}' (ID: {spreadsheet_id})"
    except Exception as e:
        return f"Erreur ajout lignes : {e}"
