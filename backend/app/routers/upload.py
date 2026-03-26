"""File upload endpoint — stores files server-side for use by agent tools (pdf_read, etc.)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.jwt import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOADS_DIR = Path("/app/uploads")
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB

# Extensions + MIME types accepted
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".csv", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".zip", ".py", ".js", ".ts", ".html", ".css",
    ".log", ".yaml", ".yml", ".toml", ".ini", ".conf",
}

_security = HTTPBearer()


async def _get_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> str:
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token invalide")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide")
    return user_id


def _safe_name(filename: str) -> str:
    """Keep only safe characters in filename."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Depends(_get_user_id),
):
    """Upload a file and return its server-side path for use by agent tools.

    Accepted: PDF, TXT, CSV, JSON, DOCX, XLSX, images and common code/config files.
    Max size: 50 MB.
    """
    original_name = file.filename or "file"
    ext = Path(original_name).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Type de fichier non pris en charge : {ext or '(sans extension)'}",
        )

    content = await file.read()
    size = len(content)

    if size == 0:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop grand ({size // (1024*1024)} MB — max 50 MB).",
        )

    # Create per-user directory
    user_dir = UPLOADS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # Store with a UUID prefix to avoid collisions
    file_id = str(uuid.uuid4())
    stored_name = f"{file_id[:8]}_{_safe_name(original_name)}"
    file_path = user_dir / stored_name
    file_path.write_bytes(content)

    logger.info("Uploaded %s (%d bytes) for user %s → %s", original_name, size, user_id, file_path)

    return {
        "file_id": file_id,
        "filename": original_name,
        "path": str(file_path),
        "size": size,
        "mime_type": file.content_type or "application/octet-stream",
    }
