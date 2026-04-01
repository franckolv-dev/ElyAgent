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
"""Google Drive tools for ELY agent — read + write."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


async def _get_drive_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
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
    service = await _get_drive_service(user_google_credentials_json)
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
    service = await _get_drive_service(user_google_credentials_json)
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


@tool
async def drive_create_folder(
    name: str,
    parent_id: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a folder in Google Drive.

    Args:
        name: Folder name
        parent_id: Optional parent folder ID (root if empty)
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        metadata: dict = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = service.files().create(body=metadata, fields="id,name,webViewLink").execute()
        return f"Dossier créé : '{folder['name']}'\nID : {folder['id']}\nLien : {folder.get('webViewLink', '—')}"
    except Exception as e:
        return f"Erreur création dossier: {e}"


@tool
async def drive_create_file(
    name: str,
    content: str,
    mime_type: str = "text/plain",
    parent_id: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a file in Google Drive with text content.

    Args:
        name: File name (e.g. "rapport.txt", "notes.md")
        content: Text content to write in the file
        mime_type: MIME type (default text/plain ; use text/csv for CSV, text/markdown for Markdown)
        parent_id: Optional parent folder ID
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload

    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        metadata: dict = {"name": name}
        if parent_id:
            metadata["parents"] = [parent_id]
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )
        file = service.files().create(
            body=metadata, media_body=media, fields="id,name,webViewLink"
        ).execute()
        return f"Fichier créé : '{file['name']}'\nID : {file['id']}\nLien : {file.get('webViewLink', '—')}"
    except Exception as e:
        return f"Erreur création fichier: {e}"


@tool
async def drive_update_file(
    file_id: str,
    content: str,
    mime_type: str = "text/plain",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update (overwrite) the content of an existing Google Drive file.

    Args:
        file_id: File ID returned by drive_list_files
        content: New text content
        mime_type: MIME type of the new content
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload

    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )
        file = service.files().update(
            fileId=file_id, media_body=media, fields="id,name,modifiedTime"
        ).execute()
        return f"Fichier mis à jour : '{file['name']}' (modifié le {file.get('modifiedTime', '?')})"
    except Exception as e:
        return f"Erreur mise à jour fichier: {e}"


@tool
async def drive_move_file(
    file_id: str,
    new_parent_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Move a file or folder to a different parent folder in Google Drive.

    Args:
        file_id: ID of the file/folder to move
        new_parent_id: ID of the destination folder
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        # Get current parents
        file = service.files().get(fileId=file_id, fields="parents,name").execute()
        previous_parents = ",".join(file.get("parents", []))
        updated = service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields="id,name,parents",
        ).execute()
        return f"'{updated['name']}' déplacé avec succès."
    except Exception as e:
        return f"Erreur déplacement: {e}"


@tool
async def drive_rename_file(
    file_id: str,
    new_name: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Rename a file or folder in Google Drive.

    Args:
        file_id: ID of the file/folder to rename
        new_name: New name
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        updated = service.files().update(
            fileId=file_id, body={"name": new_name}, fields="id,name"
        ).execute()
        return f"Renommé en '{updated['name']}' (ID: {updated['id']})"
    except Exception as e:
        return f"Erreur renommage: {e}"


@tool
async def drive_delete_file(
    file_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Move a file or folder to Google Drive Trash (does NOT permanently delete).

    Args:
        file_id: ID of the file/folder to trash
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
        return f"Fichier (ID: {file_id}) déplacé dans la corbeille Drive."
    except Exception as e:
        return f"Erreur suppression: {e}"
