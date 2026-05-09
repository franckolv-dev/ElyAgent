# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/drive_tool.py
# @brief      Google Drive tools for ELY agent — read + write.
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
"""Google Drive tools for ELY agent — read + write."""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

logger = logging.getLogger(__name__)


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
    account: Annotated[str, InjectedToolArg] = "",
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
            size = f.get("size")
            try:
                size_str = f"{int(size) // 1024} Ko"
            except (TypeError, ValueError):
                size_str = "N/A"
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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


# ──────────────────────────────────────────────────────────────────────────────
# Advanced Drive tools — sharing, copy, export, raw API
# ──────────────────────────────────────────────────────────────────────────────

_VALID_ROLES = {"reader", "commenter", "writer", "fileOrganizer", "organizer", "owner"}
_VALID_TYPES = {"user", "group", "domain", "anyone"}


@tool
async def drive_share_file(
    file_id: str,
    email_or_domain: str = "",
    role: str = "reader",
    permission_type: str = "user",
    send_notification: bool = False,
    message: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Share a Google Drive file or folder with a user, group, domain, or anyone.

    Args:
        file_id: File or folder ID.
        email_or_domain: Email (for user/group) or domain (for domain).
            Leave empty when permission_type='anyone' (link-sharing).
        role: One of 'reader', 'commenter', 'writer', 'fileOrganizer',
            'organizer', 'owner'. Default 'reader'.
        permission_type: 'user', 'group', 'domain' or 'anyone'. Default 'user'.
        send_notification: If True (user/group only), Google sends an email.
        message: Optional email notification message.
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    if role not in _VALID_ROLES:
        return f"Erreur : role invalide. Valeurs autorisées : {', '.join(sorted(_VALID_ROLES))}"
    if permission_type not in _VALID_TYPES:
        return f"Erreur : permission_type invalide. Valeurs autorisées : {', '.join(sorted(_VALID_TYPES))}"

    permission: dict = {"role": role, "type": permission_type}
    if permission_type in ("user", "group"):
        if not email_or_domain:
            return f"Erreur : email_or_domain requis pour permission_type='{permission_type}'."
        permission["emailAddress"] = email_or_domain
    elif permission_type == "domain":
        if not email_or_domain:
            return "Erreur : email_or_domain (nom de domaine) requis pour permission_type='domain'."
        permission["domain"] = email_or_domain

    kwargs: dict = {
        "fileId": file_id,
        "body": permission,
        "fields": "id,role,type,emailAddress,domain",
        "sendNotificationEmail": send_notification,
    }
    if send_notification and message:
        kwargs["emailMessage"] = message

    try:
        logger.info(
            "drive_share_file: file=%s type=%s role=%s target=%s",
            file_id, permission_type, role, email_or_domain or "anyone",
        )
        result = service.permissions().create(**kwargs).execute()
        target = result.get("emailAddress") or result.get("domain") or "anyone (lien)"
        return (
            f"✓ Permission créée sur le fichier {file_id}\n"
            f"  Type : {result.get('type')} — Rôle : {result.get('role')}\n"
            f"  Cible : {target}\n"
            f"  Permission ID : {result.get('id')}"
        )
    except Exception as e:
        logger.error("drive_share_file failed: %s", e)
        return f"Erreur partage : {e}"


@tool
async def drive_copy_file(
    file_id: str,
    new_name: str = "",
    parent_id: str = "",
    target_mime_type: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Duplicate a Google Drive file (or Docs/Sheets/Slides document).

    Args:
        file_id: ID of the file to copy.
        new_name: Name for the copy (default: "Copy of <original>")
        parent_id: Optional destination folder ID.
        target_mime_type: Convert the copy to a native Google format during
            copy. Set this to turn an uploaded Office file into a Google
            Doc/Sheet/Slide so it becomes exportable via drive_export_file.
              - 'application/vnd.google-apps.document'     (.docx  → Doc)
              - 'application/vnd.google-apps.spreadsheet'  (.xlsx  → Sheet)
              - 'application/vnd.google-apps.presentation' (.pptx  → Slides)
            Leave empty ('') to copy without conversion.
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    body: dict = {}
    if new_name:
        body["name"] = new_name
    if parent_id:
        body["parents"] = [parent_id]
    if target_mime_type:
        body["mimeType"] = target_mime_type
    try:
        copied = service.files().copy(
            fileId=file_id, body=body, fields="id,name,mimeType,webViewLink"
        ).execute()
        _conv = (
            f" (converti : {copied.get('mimeType', '?')})"
            if target_mime_type else ""
        )
        return (
            f"✓ Copie créée : '{copied['name']}'{_conv}\n"
            f"  ID : {copied['id']}\n"
            f"  Lien : {copied.get('webViewLink', '—')}"
        )
    except Exception as e:
        logger.error("drive_copy_file failed: %s", e)
        return f"Erreur copie : {e}"


@tool
async def drive_export_file(
    file_id: str,
    export_format: str = "pdf",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Export a Google Doc, Sheet or Slide to another format and save it to Drive.

    Args:
        file_id: Source Google-native file ID (Docs, Sheets or Slides).
        export_format: 'pdf', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'csv',
            'txt', 'html', 'epub', 'rtf'. Default 'pdf'.

    The exported file is saved to your Drive next to the original with the
    same title + extension.
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload

    mime_map = {
        "pdf": ("application/pdf", "pdf"),
        "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
        "odt": ("application/vnd.oasis.opendocument.text", "odt"),
        "ods": ("application/vnd.oasis.opendocument.spreadsheet", "ods"),
        "csv": ("text/csv", "csv"),
        "txt": ("text/plain", "txt"),
        "html": ("text/html", "html"),
        "epub": ("application/epub+zip", "epub"),
        "rtf": ("application/rtf", "rtf"),
    }

    fmt = export_format.lower().lstrip(".")
    if fmt not in mime_map:
        return f"Erreur : format non reconnu. Valeurs possibles : {', '.join(sorted(mime_map))}"

    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        meta = service.files().get(fileId=file_id, fields="name,parents,mimeType").execute()
        mime = meta.get("mimeType", "")
        if "google-apps" not in mime:
            return "Erreur : l'export ne fonctionne que pour les formats natifs Google (Docs, Sheets, Slides)."

        mime_out, ext = mime_map[fmt]
        logger.info("drive_export_file: file=%s to %s", file_id, fmt)
        content = service.files().export(fileId=file_id, mimeType=mime_out).execute()

        new_name = f"{meta.get('name', 'export')}.{ext}"
        body: dict = {"name": new_name}
        if meta.get("parents"):
            body["parents"] = meta["parents"]

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_out, resumable=False)
        created = service.files().create(
            body=body, media_body=media, fields="id,name,webViewLink"
        ).execute()
        return (
            f"✓ Export {fmt} créé : '{created['name']}'\n"
            f"  ID : {created['id']}\n"
            f"  Lien : {created.get('webViewLink', '—')}"
        )
    except Exception as e:
        logger.error("drive_export_file failed: %s", e)
        return f"Erreur export : {e}"


@tool
async def drive_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Google Drive API (v3) directly.

    Escape hatch for advanced Drive operations: permissions management,
    revisions, comments, shared drives, about.get, file watch, etc.

    Args:
        method_path: Dot-separated Drive API method, e.g.
            'files.list', 'files.get', 'permissions.list',
            'permissions.delete', 'revisions.list', 'revisions.delete',
            'comments.create', 'about.get', 'drives.list'.
        params_json: JSON object of kwargs.
            Example: '{"fileId": "abc", "permissionId": "xyz"}'
        body_json: Optional JSON body for POST/PATCH methods.
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "drive")


# ──────────────────────────────────────────────────────────────────────────────
# drive_find_duplicates — server-side duplicate detection
#
# Why a dedicated tool ?
# Asking the LLM to « identify duplicates in /perso » means:
#   1. recursive listing (10+ folders × 50 files = 500+ entries)
#   2. comparing names/sizes/dates pairwise in working memory
#   3. reasoning over a JSON blob too large for any 8-24B local model
# Even Qwen Flash hits 5+ tool_calls and confabulates. Ministral 14B
# OOM'd on Metal after 21 messages (mai 2026 incident).
#
# Design:
#   - Server-side recursive walk via Drive API (paginated)
#   - Group by md5Checksum (free field on binary files in Drive API v3)
#   - Optional fallback to (name + size) for native Google formats which
#     have no md5 (Docs, Sheets, Slides — Drive doesn't expose checksums)
#   - Return ONLY the duplicate groups, never the full file list
#   - Compact human-readable format for the LLM to forward
#
# This compresses ~500 file entries into <50 lines — tractable for any LLM.
# ──────────────────────────────────────────────────────────────────────────────


@tool
async def drive_find_duplicates(
    folder_id: str,
    recursive: bool = True,
    by: str = "md5",
    max_files: int = 2000,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Find duplicate files in a Google Drive folder. Server-side hashing.

    👉 USE THIS TOOL whenever the user asks to find/identify/list duplicate
    files in their Drive. NEVER try to do it via repeated drive_list_files
    + manual comparison — it doesn't scale beyond ~10 files and hallucinates.

    Args:
        folder_id: Drive folder ID where to search (NOT the folder name).
            Get it first via drive_list_files(query="name='myfolder' and
            mimeType='application/vnd.google-apps.folder'").
            For the user's root, use 'root'.
        recursive: If True (default), explore subfolders too. If False,
            only files directly in folder_id.
        by: Duplicate detection strategy:
            - 'md5'       (default) — MD5 checksum match. Most reliable
              but only works for binary files (photos, PDFs, archives,
              videos). Google-native formats (Docs, Sheets) are skipped.
            - 'name'      — Identical filename match. Detects user-renamed
              copies but generates false positives.
            - 'name+size' — Same name AND same byte size. Best for native
              Google docs which have no MD5 checksum.
        max_files: Hard cap on the recursive walk (default 2000). Increase
            for very large drives, decrease for quick scans.

    Returns: a compact human-readable report — only the duplicate groups,
    not the full file list. Format example:
        Group 1 (3 copies, 2.4 MB each):
          - photo.jpg (folder: vacation/2024)
          - photo (1).jpg (folder: vacation/2024)
          - copy_photo.jpg (folder: backup)

    If nothing is duplicated, returns « Aucun doublon trouvé ».
    """
    service = await _get_drive_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    by = (by or "md5").lower().strip()
    if by not in {"md5", "name", "name+size"}:
        return f"Paramètre 'by' invalide: '{by}'. Valeurs: 'md5', 'name', 'name+size'."

    max_files = max(10, min(int(max_files), 10000))

    # Recursive BFS walk to collect all files. Folders are explored in turn,
    # files are accumulated. We track parent path for human-readable output.
    try:
        # path_by_id maps folder_id → human path ("perso/vacation/2024")
        # so the final report can show where each file lives.
        path_by_id: dict[str, str] = {folder_id: ""}
        folders_to_visit: list[str] = [folder_id]
        all_files: list[dict] = []
        visited_folders: set[str] = set()

        while folders_to_visit and len(all_files) < max_files:
            current = folders_to_visit.pop(0)
            if current in visited_folders:
                continue
            visited_folders.add(current)
            current_path = path_by_id.get(current, "")

            page_token: str | None = None
            while True:
                resp = service.files().list(
                    q=f"'{current}' in parents and trashed=false",
                    pageSize=200,
                    fields=(
                        "nextPageToken, "
                        "files(id, name, mimeType, modifiedTime, "
                        "size, md5Checksum)"
                    ),
                    pageToken=page_token,
                ).execute()
                for f in resp.get("files", []):
                    if f.get("mimeType") == "application/vnd.google-apps.folder":
                        if recursive:
                            child_path = (
                                f"{current_path}/{f['name']}" if current_path
                                else f["name"]
                            )
                            path_by_id[f["id"]] = child_path
                            folders_to_visit.append(f["id"])
                    else:
                        f["_path"] = current_path or "(racine)"
                        all_files.append(f)
                        if len(all_files) >= max_files:
                            break
                page_token = resp.get("nextPageToken")
                if not page_token or len(all_files) >= max_files:
                    break

        if not all_files:
            return f"Aucun fichier trouvé dans le dossier (id={folder_id})."

        # Group by the chosen strategy. Keep only groups with >= 2 entries.
        groups: dict[tuple, list[dict]] = {}
        skipped_no_hash = 0
        for f in all_files:
            if by == "md5":
                key = f.get("md5Checksum")
                if not key:
                    skipped_no_hash += 1
                    continue
                key = ("md5", key)
            elif by == "name":
                key = ("name", f["name"].lower().strip())
            else:  # name+size
                size = f.get("size") or "0"
                key = ("name+size", f["name"].lower().strip(), str(size))
            groups.setdefault(key, []).append(f)

        dup_groups = [g for g in groups.values() if len(g) >= 2]
        dup_groups.sort(key=lambda g: -len(g))  # biggest groups first

        if not dup_groups:
            footer = ""
            if skipped_no_hash and by == "md5":
                footer = (
                    f"\n\nNote: {skipped_no_hash} fichier(s) Google natif(s) "
                    f"(Docs, Sheets, Slides) ignoré(s) — pas de checksum MD5. "
                    f"Relance avec by='name+size' pour les inclure."
                )
            return (
                f"✅ Aucun doublon trouvé sur {len(all_files)} fichier(s) "
                f"explorés (stratégie: {by}).{footer}"
            )

        # Build the report. Cap details to avoid context bloat: show all
        # groups but cap individual file lists at 8 entries per group.
        total_dups = sum(len(g) - 1 for g in dup_groups)
        lines = [
            f"🔍 **{len(dup_groups)} groupe(s) de doublons** détecté(s) "
            f"sur {len(all_files)} fichier(s) explorés "
            f"(stratégie: {by}, {total_dups} fichier(s) en trop) :",
            "",
        ]
        for i, group in enumerate(dup_groups, 1):
            sample = group[0]
            try:
                sample_size_kb = int(sample.get("size") or 0) // 1024
                size_str = f"{sample_size_kb} Ko" if sample_size_kb else "N/A"
            except (TypeError, ValueError):
                size_str = "N/A"
            lines.append(
                f"**Groupe {i}** — {len(group)} copies, ~{size_str} chacune :"
            )
            for f in group[:8]:
                lines.append(
                    f"  • {f['name']} (dossier: {f['_path']}) "
                    f"[id: {f['id']}]"
                )
            if len(group) > 8:
                lines.append(f"  … et {len(group) - 8} autre(s)")
            lines.append("")

        if skipped_no_hash and by == "md5":
            lines.append(
                f"_Note: {skipped_no_hash} fichier(s) Google natif(s) "
                f"ignoré(s) — pas de MD5. Relance avec by='name+size' "
                f"pour les inclure._"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.warning("drive_find_duplicates failed: %s", e)
        return f"Erreur drive_find_duplicates: {e}"
