# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/upload.py
# @brief      File upload endpoint — stores files server-side for use by agent tools (pdf_read, etc.).
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
"""File upload endpoint — stores files server-side for use by agent tools (pdf_read, etc.)."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.jwt import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).parents[2] / "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB

# B-9 (revue 2026-06-10) — quota disque PAR USER. La limite par fichier
# existait mais rien ne bornait le cumul : N users × captures d'écran à
# chaque message + uploads 50 Mo = croissance non bornée sur le disque hôte.
# 0 = désactivé.
UPLOAD_QUOTA_MB = int(os.environ.get("ELY_UPLOAD_QUOTA_MB", "500"))

# Purge des fichiers plus vieux que N jours (cron quotidien programmé dans
# main.py). 90 j par défaut : les chemins restent référencés dans
# l'historique des conversations — une purge agressive casserait des liens
# encore consultés. 0 = désactivé.
UPLOADS_RETENTION_DAYS = int(os.environ.get("ELY_UPLOADS_RETENTION_DAYS", "90"))


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _check_user_quota(user_dir: Path, incoming_size: int) -> None:
    """Raise 413 when accepting ``incoming_size`` would exceed the per-user
    quota. Separate helper so the policy is unit-testable without the
    HTTP/auth round-trip."""
    if UPLOAD_QUOTA_MB <= 0:
        return
    quota = UPLOAD_QUOTA_MB * 1024 * 1024
    used = _dir_size_bytes(user_dir)
    if used + incoming_size > quota:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Quota de stockage atteint ({used // (1024*1024)} Mo utilisés "
                f"sur {UPLOAD_QUOTA_MB} Mo). Supprime des fichiers ou augmente "
                f"ELY_UPLOAD_QUOTA_MB."
            ),
        )


async def purge_old_uploads() -> int:
    """Delete uploaded files older than the retention window.

    Scheduled daily from main.py (B-9). Runs the filesystem scan in a
    thread — UPLOADS_DIR can hold thousands of screenshots."""
    if UPLOADS_RETENTION_DAYS <= 0:
        return 0
    cutoff = time.time() - UPLOADS_RETENTION_DAYS * 86400

    def _scan() -> int:
        removed = 0
        if not UPLOADS_DIR.exists():
            return 0
        for f in UPLOADS_DIR.rglob("*"):
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        # Élague les sous-dossiers d'upload devenus vides (un dossier par
        # upload depuis le fix « isolation des pièces jointes » — sans ça,
        # des milliers de dossiers vides s'accumulent au rythme des purges).
        # rmdir ne supprime que les dossiers vides ; tri inversé = enfants
        # d'abord. Un dossier user vidé est recréé au prochain upload.
        for d in sorted(
            (p for p in UPLOADS_DIR.rglob("*") if p.is_dir()), reverse=True
        ):
            try:
                d.rmdir()
            except OSError:
                continue
        return removed

    removed = await asyncio.to_thread(_scan)
    if removed:
        logger.info(
            "uploads purge: %d fichier(s) > %d jours supprimés",
            removed, UPLOADS_RETENTION_DAYS,
        )
    return removed

# Extensions + MIME types accepted
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".csv", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".zip", ".py", ".js", ".ts", ".html", ".css",
    ".log", ".yaml", ".yml", ".toml", ".ini", ".conf",
}

_security = HTTPBearer()

# Magic bytes for dangerous file types that should never be uploaded
_DANGEROUS_MAGIC: list[bytes] = [
    b"<?php",          # PHP scripts
    b"<script",        # standalone JS/HTML script tags
    b"<!doctype html", # HTML documents (case-insensitive check below)
    b"<!DOCTYPE html",
    b"<html",
    b"MZ",             # Windows PE executables
    b"\x7fELF",        # Linux/ELF executables
    b"\xca\xfe\xba\xbe",  # macOS universal binary / Java .class
    b"PK\x03\x04",    # ZIP — allowed by extension, verified below via ext allowlist
]

# Extensions that must NOT contain binary executable magic bytes
_BINARY_EXEC_MAGIC = (b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe")


def _verify_file_content(file_bytes: bytes, filename: str) -> bool:
    """Return False if the file content looks dangerous regardless of extension."""
    header = file_bytes[:16]
    # Check for binary executables unconditionally
    for magic in _BINARY_EXEC_MAGIC:
        if header[: len(magic)] == magic:
            return False
    # Check for server-side script types
    header_lower = header.lower()
    for magic in (b"<?php", b"<script", b"<!doctype html", b"<html"):
        if header_lower.startswith(magic):
            return False
    return True


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

    # MED-6: Verify content magic bytes before saving
    if not _verify_file_content(content, original_name):
        raise HTTPException(
            status_code=415,
            detail="Contenu de fichier refusé — type d'exécutable ou de script non autorisé.",
        )

    # Create per-user directory
    user_dir = UPLOADS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # B-9 — quota par user (le scan disque part en thread, pas sur la loop)
    await asyncio.to_thread(_check_user_quota, user_dir, size)

    # Un sous-dossier par upload (au lieu d'un stockage à plat) : quand Ely
    # passe le dossier PARENT d'une pièce jointe à un outil « dossier »
    # (ex. MCP translate_pdf_folder(input_dir=…)), il ne doit contenir que
    # la pièce jointe de la demande en cours — pas tout l'historique
    # d'uploads (incident 17/07 : manuscrit 400 p. mis en traduction 3×
    # + 4 PDF sans rapport). Le nom d'origine est conservé dans le
    # sous-dossier : plus lisible pour les outils et l'utilisateur.
    file_id = str(uuid.uuid4())
    safe_name = _safe_name(original_name)
    if safe_name in ("", ".", ".."):
        safe_name = "file"
    upload_dir = user_dir / file_id[:8]
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / safe_name
    file_path.write_bytes(content)

    logger.info("Uploaded %s (%d bytes) for user %s → %s", original_name, size, user_id, file_path)

    return {
        "file_id": file_id,
        "filename": original_name,
        "path": str(file_path),
        "size": size,
        "mime_type": file.content_type or "application/octet-stream",
    }
