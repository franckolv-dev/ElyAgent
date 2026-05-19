# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/knowledge.py
# @brief      Knowledge base REST endpoints — ingest, search, list, delete documents.
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
