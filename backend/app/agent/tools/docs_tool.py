"""Google Docs tools for ELY agent — create and edit documents."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


def _get_docs_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = get_user_credentials(user_google_credentials_json)
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
) -> str:
    """Create a new Google Docs document (equivalent to a Word document).

    Args:
        title: Document title
        content: Initial text content (optional). Use \\n for line breaks.
    """
    service = _get_docs_service(user_google_credentials_json)
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
) -> str:
    """Read the text content of a Google Docs document.

    Args:
        document_id: The document ID (from the URL or docs_create_document)
    """
    service = _get_docs_service(user_google_credentials_json)
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
) -> str:
    """Append text at the end of an existing Google Docs document.

    Args:
        document_id: The document ID
        text: Text to append. Use \\n for line breaks.
    """
    service = _get_docs_service(user_google_credentials_json)
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
