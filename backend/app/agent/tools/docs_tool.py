# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/docs_tool.py
# @brief      Google Docs tools for ELY agent — create and edit documents.
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
"""Google Docs tools for ELY agent — create and edit documents."""
from __future__ import annotations

import json
import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

logger = logging.getLogger(__name__)


async def _get_docs_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("docs", "v1", credentials=creds)


def _extract_text(doc: dict) -> str:
    """Extract plain text from a Google Doc structure."""
    text = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for part in element["paragraph"].get("elements", []):
                if "textRun" in part:
                    text += part["textRun"].get("content", "")
    return text


@tool
async def docs_create_document(
    title: str,
    content: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new Google Docs document (equivalent to a Word document).

    Args:
        title: Document title
        content: Initial text content (optional). Use \\n for line breaks.
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        doc = service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        url = f"https://docs.google.com/document/d/{doc_id}/edit"

        if content:
            service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()

        return f"Document créé : '{title}'\nURL : {url}\nID : {doc_id}"
    except Exception as e:
        return f"Erreur création document : {e}"


@tool
async def docs_read_document(
    document_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the text content of a Google Docs document.

    Args:
        document_id: The document ID (from the URL or docs_create_document)
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        doc = service.documents().get(documentId=document_id).execute()
        title = doc.get("title", "Sans titre")
        text = _extract_text(doc)
        return f"Document : '{title}'\n\n{text[:5000]}"
    except Exception as e:
        return f"Erreur lecture document : {e}"


@tool
async def docs_append_text(
    document_id: str,
    text: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Append text at the end of an existing Google Docs document.

    Args:
        document_id: The document ID
        text: Text to append. Use \\n for line breaks.
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        doc = service.documents().get(documentId=document_id).execute()
        # Find end index
        content = doc.get("body", {}).get("content", [])
        end_index = content[-1].get("endIndex", 1) - 1 if content else 1

        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": end_index}, "text": text}}]},
        ).execute()

        title = doc.get("title", "Sans titre")
        return f"Texte ajouté au document '{title}' (ID: {document_id})"
    except Exception as e:
        return f"Erreur modification document : {e}"


@tool
async def docs_replace_text(
    document_id: str,
    find_text: str,
    replace_text: str,
    match_case: bool = True,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Replace all occurrences of a text string in a Google Docs document.

    Args:
        document_id: The document ID
        find_text: The text to find
        replace_text: The replacement text
        match_case: Whether the search is case-sensitive (default True)
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": find_text,
                                "matchCase": match_case,
                            },
                            "replaceText": replace_text,
                        }
                    }
                ]
            },
        ).execute()

        replies = result.get("replies", [{}])
        count = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return f"{count} remplacement(s) effectué(s) dans le document (ID: {document_id})"
    except Exception as e:
        return f"Erreur remplacement texte : {e}"


@tool
async def docs_insert_table(
    document_id: str,
    rows: int,
    columns: int,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Insert a table at the end of a Google Docs document.

    Args:
        document_id: The document ID
        rows: Number of rows
        columns: Number of columns
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        doc = service.documents().get(documentId=document_id).execute()
        content = doc.get("body", {}).get("content", [])
        end_index = content[-1].get("endIndex", 1) - 1 if content else 1

        service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertTable": {
                            "rows": rows,
                            "columns": columns,
                            "location": {"index": end_index},
                        }
                    }
                ]
            },
        ).execute()

        return f"Tableau {rows}x{columns} inséré dans le document (ID: {document_id})"
    except Exception as e:
        return f"Erreur insertion tableau : {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Generic batch / raw API tools — unlocks ANY Docs operation
# ──────────────────────────────────────────────────────────────────────────────

_DOCS_BATCH_UPDATE_GUIDE = """
Types de requêtes Docs les plus utiles (liste `requests`) :

• Insérer du texte à une position
  {"insertText": {"location": {"index": 1}, "text": "Bonjour\\n"}}

• Supprimer une plage
  {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 20}}}

• Appliquer un style de texte (gras, italique, couleur, taille)
  {"updateTextStyle": {
      "range": {"startIndex": 1, "endIndex": 50},
      "textStyle": {"bold": true, "italic": false,
                    "fontSize": {"magnitude": 14, "unit": "PT"},
                    "foregroundColor": {"color": {"rgbColor":
                        {"red": 0.8, "green": 0.0, "blue": 0.0}}}},
      "fields": "bold,italic,fontSize,foregroundColor"}}

• Appliquer un style de paragraphe (Titre, alignement, espacement)
  {"updateParagraphStyle": {
      "range": {"startIndex": 1, "endIndex": 50},
      "paragraphStyle": {"namedStyleType": "HEADING_1",
                          "alignment": "CENTER"},
      "fields": "namedStyleType,alignment"}}

• Listes à puces / numérotées
  {"createParagraphBullets": {
      "range": {"startIndex": 1, "endIndex": 50},
      "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}}

• Insérer un tableau
  {"insertTable": {"rows": 3, "columns": 2, "location": {"index": 1}}}

• Saut de page
  {"insertPageBreak": {"location": {"index": 1}}}

• Insérer une image
  {"insertInlineImage": {"location": {"index": 1},
                          "uri": "https://example.com/image.png"}}

• Remplacer du texte (global)
  {"replaceAllText": {"containsText": {"text": "ancien", "matchCase": false},
                       "replaceText": "nouveau"}}

• Créer un lien
  {"updateTextStyle": {
      "range": {"startIndex": 1, "endIndex": 10},
      "textStyle": {"link": {"url": "https://exemple.fr"}},
      "fields": "link"}}

Positions (`index`) : 1 = début du corps. Pour ajouter en fin,
lire d'abord le doc via `docs_read_document` et calculer l'endIndex.
"""


@tool
async def docs_batch_update(
    document_id: str,
    requests_json: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Execute one or more advanced operations on a Google Docs document.

    Gives access to the FULL `documents.batchUpdate` API: text styling
    (bold, italic, colors, font size), paragraph styling (headings,
    alignment), bulleted/numbered lists, page breaks, images, replaceAllText,
    hyperlinks, named ranges, table manipulation, etc.

    Args:
        document_id: The document ID.
        requests_json: JSON array of Docs batchUpdate requests.
            Example — make first 10 chars bold:
              '[{"updateTextStyle": {"range": {"startIndex": 1, "endIndex": 11},
              "textStyle": {"bold": true}, "fields": "bold"}}]'
    """
    service = await _get_docs_service(user_google_credentials_json)
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
            "docs_batch_update: document=%s, %d request(s), types=%s",
            document_id, len(requests),
            [list(r.keys())[0] if isinstance(r, dict) and r else "?" for r in requests],
        )
        result = service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()

        replies = result.get("replies", [])
        lines = [f"✓ {len(replies)} opération(s) exécutée(s) sur le document {document_id}"]
        for i, reply in enumerate(replies):
            if not reply:
                continue
            op = list(reply.keys())[0] if reply else None
            if op == "replaceAllText":
                n = reply["replaceAllText"].get("occurrencesChanged", 0)
                lines.append(f"  [{i}] replaceAllText → {n} occurrence(s)")
            elif op:
                lines.append(f"  [{i}] {op}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("docs_batch_update failed: %s", e)
        return f"Erreur docs_batch_update : {e}"


docs_batch_update.description = (docs_batch_update.description or "") + _DOCS_BATCH_UPDATE_GUIDE


@tool
async def docs_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Google Docs API (v1) directly.

    Escape hatch for operations not covered by dedicated tools. Prefer
    `docs_batch_update` for document mutations.

    Args:
        method_path: Dot-separated Docs API method, e.g. 'documents.get',
            'documents.create', 'documents.batchUpdate'.
        params_json: JSON object of kwargs (e.g. '{"documentId": "abc"}').
        body_json: Optional JSON body for POST/PATCH methods.
    """
    service = await _get_docs_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "docs")
