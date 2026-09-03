# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/knowledge.py
# @brief      Knowledge base REST endpoints — ingest, search, list, delete documents.
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
"""Knowledge base REST endpoints — ingest, search, list, delete documents."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.routers.upload import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    UPLOADS_DIR,
    _safe_name,
    _verify_file_content,
)
from app.services.rag_service import get_rag_service

router = APIRouter()
logger = logging.getLogger(__name__)

# File types supported for RAG ingestion
_RAG_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".csv", ".json",
    ".doc", ".docx",
    ".xls", ".xlsx",
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    limit: int = 5


class SearchResult(BaseModel):
    content: str
    title: str
    source_file: str
    chunk_index: int
    score: float


class DocumentInfo(BaseModel):
    document_id: str
    title: str
    source_file: str
    chunk_count: int
    created_at: float | None = None


class IngestResponse(BaseModel):
    document_id: str
    title: str
    chunk_count: int
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/knowledge/ingest", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(...),
    title: str | None = Query(None, description="Titre du document (optionnel)"),
    collection: str | None = Query(None, description="Collection Qdrant (optionnel)"),
    user: User = Depends(get_current_user),
):
    """Upload and ingest a document into the knowledge base.

    Supported formats: PDF, TXT, MD, CSV, JSON, DOCX.
    The document is chunked, embedded, and stored in Qdrant for semantic search.
    """
    import uuid

    original_name = file.filename or "file"
    ext = Path(original_name).suffix.lower()

    # Validate extension (must be both in ALLOWED_EXTENSIONS and _RAG_EXTENSIONS)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Type de fichier non pris en charge : {ext or '(sans extension)'}",
        )
    if ext not in _RAG_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Type de fichier non supporte pour l'indexation RAG : {ext}. "
                   f"Formats acceptes : {', '.join(sorted(_RAG_EXTENSIONS))}",
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

    # Security: verify file content magic bytes
    if not _verify_file_content(content, original_name):
        raise HTTPException(
            status_code=415,
            detail="Contenu de fichier refuse — type d'executable ou de script non autorise.",
        )

    # Save file to disk (reuse upload directory structure)
    user_dir = UPLOADS_DIR / user.id
    user_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    stored_name = f"{file_id[:8]}_{_safe_name(original_name)}"
    file_path = user_dir / stored_name
    file_path.write_bytes(content)

    logger.info(
        "Knowledge ingest: %s (%d bytes) for user %s → %s",
        original_name, size, user.id, file_path,
    )

    # Ingest into RAG pipeline
    try:
        rag = get_rag_service()
        result = await rag.ingest_document(
            file_path=file_path,
            user_id=user.id,
            title=title,
            collection_name=collection,
        )
        return IngestResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Ingestion failed for %s: %s", original_name, exc)
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de l'indexation du document. Veuillez réessayer.",
        )


@router.get("/knowledge/documents", response_model=list[DocumentInfo])
async def list_documents(user: User = Depends(get_current_user)):
    """List all documents in the user's knowledge base."""
    rag = get_rag_service()
    docs = await rag.list_documents(user.id)
    return [DocumentInfo(**d) for d in docs]


@router.delete("/knowledge/documents/{document_id}")
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a document and all its chunks from the knowledge base."""
    rag = get_rag_service()

    # Verify the document exists and belongs to this user
    info = await rag.get_document_info(document_id, user.id)
    if info is None:
        raise HTTPException(status_code=404, detail="Document non trouve.")

    success = await rag.delete_document(document_id, user.id)
    if not success:
        raise HTTPException(status_code=500, detail="Erreur lors de la suppression du document.")

    return {"status": "deleted", "document_id": document_id}


@router.post("/knowledge/search", response_model=list[SearchResult])
async def search_knowledge(
    body: SearchRequest,
    user: User = Depends(get_current_user),
):
    """Search the knowledge base using semantic similarity."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="La requete de recherche ne peut pas etre vide.")

    rag = get_rag_service()
    results = await rag.search_knowledge(
        query=body.query,
        user_id=user.id,
        limit=body.limit,
    )
    _fields = set(SearchResult.model_fields)
    return [SearchResult(**{k: v for k, v in r.items() if k in _fields}) for r in results]


# ──────────────────────────────────────────────────────────────────────────────
# Watched folders — auto-indexing of local folders into the RAG knowledge base
# ──────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from sqlalchemy import select as _select_wf
from app.database import async_session as _async_session_wf
from app.models.watched_folder import (
    WatchedFolder,
    DEFAULT_INCLUDE_EXTENSIONS,
    DEFAULT_EXCLUDE_PATHS,
)


class _WatchedFolderOut(BaseModel):
    id: str
    path: str
    recursive: bool
    enabled: bool
    include_extensions: str
    exclude_paths: str
    last_scan_at: str | None
    last_scan_status: str
    last_scan_message: str
    files_indexed: int
    created_at: str


class _WatchedFolderCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    recursive: bool = True
    include_extensions: str = DEFAULT_INCLUDE_EXTENSIONS
    exclude_paths: str = DEFAULT_EXCLUDE_PATHS


class _WatchedFolderUpdate(BaseModel):
    enabled: bool | None = None
    recursive: bool | None = None
    include_extensions: str | None = None
    exclude_paths: str | None = None


def _wf_to_dict(f: WatchedFolder) -> dict:
    return {
        "id": f.id,
        "path": f.path,
        "recursive": f.recursive,
        "enabled": f.enabled,
        "include_extensions": f.include_extensions,
        "exclude_paths": f.exclude_paths,
        "last_scan_at": f.last_scan_at.isoformat() if f.last_scan_at else None,
        "last_scan_status": f.last_scan_status,
        "last_scan_message": f.last_scan_message,
        "files_indexed": f.files_indexed,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.get("/knowledge/watched-folders")
async def list_watched_folders(user: User = Depends(get_current_user)):
    """List every folder this user has set up for auto-indexing."""
    async with _async_session_wf() as db:
        rows = await db.execute(
            _select_wf(WatchedFolder)
            .where(WatchedFolder.user_id == user.id)
            .order_by(WatchedFolder.created_at.asc())
        )
        return {"folders": [_wf_to_dict(f) for f in rows.scalars()]}


@router.post("/knowledge/watched-folders")
async def create_watched_folder(
    req: _WatchedFolderCreate,
    user: User = Depends(get_current_user),
):
    """Register a new folder for auto-indexing.

    Does NOT scan immediately — call ``POST /knowledge/watched-folders/{id}/scan``
    or wait for the cron tick. This split avoids a 30-second HTTP request
    on first add.
    """
    async with _async_session_wf() as db:
        # Reject duplicate (user_id, path) explicitly so the UI can show a
        # nice error instead of a 500 from the DB constraint.
        existing = await db.execute(
            _select_wf(WatchedFolder).where(
                WatchedFolder.user_id == user.id,
                WatchedFolder.path == req.path,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Folder already watched: {req.path}")

        f = WatchedFolder(
            user_id=user.id,
            path=req.path.strip(),
            recursive=req.recursive,
            include_extensions=req.include_extensions or DEFAULT_INCLUDE_EXTENSIONS,
            exclude_paths=req.exclude_paths or DEFAULT_EXCLUDE_PATHS,
            enabled=True,
            last_scan_status="pending",
            last_scan_message="",
        )
        db.add(f)
        await db.flush()
        await db.refresh(f)
        await db.commit()
        return _wf_to_dict(f)


@router.patch("/knowledge/watched-folders/{folder_id}")
async def update_watched_folder(
    folder_id: str,
    req: _WatchedFolderUpdate,
    user: User = Depends(get_current_user),
):
    """Toggle enabled/recursive or update extension filters."""
    async with _async_session_wf() as db:
        f = await db.get(WatchedFolder, folder_id)
        if not f or f.user_id != user.id:
            raise HTTPException(status_code=404, detail="Folder not found")
        if req.enabled is not None:
            f.enabled = req.enabled
        if req.recursive is not None:
            f.recursive = req.recursive
        if req.include_extensions is not None:
            f.include_extensions = req.include_extensions or DEFAULT_INCLUDE_EXTENSIONS
        if req.exclude_paths is not None:
            f.exclude_paths = req.exclude_paths or DEFAULT_EXCLUDE_PATHS
        await db.commit()
        await db.refresh(f)
        return _wf_to_dict(f)


@router.delete("/knowledge/watched-folders/{folder_id}")
async def delete_watched_folder(
    folder_id: str,
    user: User = Depends(get_current_user),
):
    """Remove a watched folder. Does NOT delete ingested chunks from Qdrant —
    use the existing ``DELETE /knowledge/documents/{id}`` for that, per-document.
    """
    async with _async_session_wf() as db:
        f = await db.get(WatchedFolder, folder_id)
        if not f or f.user_id != user.id:
            raise HTTPException(status_code=404, detail="Folder not found")
        await db.delete(f)
        await db.commit()
        return {"message": "Folder removed", "id": folder_id}


@router.post("/knowledge/watched-folders/{folder_id}/scan")
async def scan_watched_folder_now(
    folder_id: str,
    user: User = Depends(get_current_user),
):
    """Trigger an immediate scan of a watched folder. Returns when done.

    Long-running (can take 30s+ on a folder with many files). The UI
    should show a spinner. Concurrency is handled in the service layer
    (mutex per folder).
    """
    async with _async_session_wf() as db:
        f = await db.get(WatchedFolder, folder_id)
        if not f or f.user_id != user.id:
            raise HTTPException(status_code=404, detail="Folder not found")

    from app.services.auto_indexer import scan_folder
    summary = await scan_folder(folder_id)
    return summary
