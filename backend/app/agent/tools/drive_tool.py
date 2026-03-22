"""Google Drive tools for ELY agent — read-only by default."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


def _get_drive_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("drive", "v3", credentials=creds)


@tool
async def drive_list_files(
    query: str = "",
    max_results: int = 10,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List files in Google Drive.

    Args:
        query: Drive search query (e.g. 'name contains "rapport"', 'mimeType="application/pdf"')
        max_results: Number of files to return (default 10)
    """
    service = _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        params = {
            "pageSize": min(max_results, 50),
            "fields": "files(id, name, mimeType, modifiedTime, size)",
        }
        if query:
            params["q"] = query

        result = service.files().list(**params).execute()
        files = result.get("files", [])

        if not files:
            return "Aucun fichier trouvé."

        lines = []
        for f in files:
            size = f.get("size", "?")
            size_str = f"{int(size) // 1024} Ko" if size != "?" else "?"
            lines.append(
                f"• {f['name']} ({f.get('mimeType', '?')})\n"
                f"  Modifié: {f.get('modifiedTime', '?')} | Taille: {size_str}\n"
                f"  ID: {f['id']}"
            )

        return f"{len(files)} fichier(s):\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"Erreur Drive: {e}"


@tool
async def drive_read_file(
    file_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the text content of a Google Drive file (Docs, text files).

    Args:
        file_id: The file ID returned by drive_list_files
    """
    service = _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
        mime = meta.get("mimeType", "")

        if "google-apps.document" in mime:
            content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            return f"Contenu de '{meta['name']}':\n\n{content.decode('utf-8', errors='replace')[:4000]}"
        elif "google-apps" in mime:
            return f"Fichier '{meta['name']}' ({mime}) — format non exportable en texte."
        else:
            content = service.files().get_media(fileId=file_id).execute()
            text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            return f"Contenu de '{meta['name']}':\n\n{text[:4000]}"
    except Exception as e:
        return f"Erreur lecture fichier: {e}"
