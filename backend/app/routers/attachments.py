# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/attachments.py
# @brief      Serve attachment files (screenshots, generated images, etc.)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""REST endpoint to serve attachments referenced via the MEDIA: sentinel.

Frontend receives ``attachments=[{path:..., filename:..., mime_type:...,
exp:..., sig:...}]`` in the WebSocket payload and fetches the file via
``/api/attachments/?path=...&exp=...&sig=...``.

Security
--------
- **HMAC-signed URL** (24h TTL): each attachment URL carries an ``exp``
  expiry timestamp and a ``sig`` HMAC over ``path|exp`` keyed off the
  JWT secret. The endpoint refuses requests with invalid or expired
  signatures. We use signed URLs (not cookie auth) because ``<img>``
  tags can't reliably send credentials cross-origin.
- Path whitelist: only files under ``_ALLOWED_DIRS`` are served, with
  realpath resolution to defeat symlinks.
- Extension whitelist: only image/pdf/text MIME-types served.
- Path traversal: ``..`` and NUL byte in ``path`` rejected immediately.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.media_router import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


_ALLOWED_DIRS: Final[tuple[str, ...]] = (
    "/tmp/ely-attachments",
    "/data/attachments",
    "/app/data/attachments",
    # Sorties bureautiques d'Ely (pdf_to_docx écrit ici). Sans ce répertoire,
    # le fichier est produit puis reste inatteignable — constat d'audit 25/07.
    # Dérivé du tempdir SYSTÈME comme le producteur : "/tmp" en conteneur
    # Linux, "/var/folders/…" sur macOS — un chemin en dur casserait hors
    # Docker (et les tests avec).
    str(Path(tempfile.gettempdir()) / "ely-docx"),
)

_ALLOWED_EXTS: Final[frozenset[str]] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".txt", ".md", ".csv", ".json",
    # Bureautique : ce qu'Ely sait produire (docx) et ce qu'un utilisateur
    # s'attend à pouvoir ouvrir. La liste reste une liste BLANCHE — aucun
    # exécutable, aucun script.
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".epub",
})


def _resolve_safe_path(raw_path: str) -> Path:
    """Resolve and validate that ``raw_path`` is under a whitelisted dir.

    Raises HTTPException(400) on invalid input, HTTPException(404) if the
    file does not exist or extension is not allowed.
    """
    if not raw_path or ".." in raw_path or "\x00" in raw_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    norm = os.path.normpath(raw_path)
    if not any(
        norm.startswith(d + os.sep) or norm == d for d in _ALLOWED_DIRS
    ):
        raise HTTPException(status_code=403, detail="Path outside whitelist")
    p = Path(norm)
    if p.suffix.lower() not in _ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail="Extension not allowed")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Final realpath check (defeat symlinks pointing outside whitelist)
    real = p.resolve(strict=False)
    if not any(
        str(real).startswith(d + os.sep) or str(real) == d
        for d in _ALLOWED_DIRS
    ):
        raise HTTPException(status_code=403, detail="Symlink escapes whitelist")
    return p


@router.get("/")
async def get_attachment(
    path: str = Query(..., description="Absolute path returned by the WebSocket payload"),
    exp: int = Query(..., description="Signed URL expiry timestamp (Unix seconds)"),
    sig: str = Query(..., description="HMAC-SHA256 signature over path|exp"),
):
    """Stream the requested attachment file (HMAC-signed URL)."""
    if not verify_signature(path, exp, sig):
        # Don't leak whether expiry vs sig is wrong — uniform 403.
        raise HTTPException(status_code=403, detail="Invalid or expired signature")
    p = _resolve_safe_path(path)
    logger.info("attachments: serving %s", p)
    return FileResponse(
        path=str(p),
        filename=p.name,
        # Inline so <img src="..."> renders directly; browsers still allow
        # right-click "save as" for PDFs and other types.
    )
