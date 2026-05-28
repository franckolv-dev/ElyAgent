# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/conversations.py
# @brief      Conversations API — list, search, rename, delete and export conversations.
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Conversations API — list, search, rename, delete and export conversations."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.conversation import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class RenameBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_owned_conversation(db, conversation_id: str, user_id: str) -> Conversation:
    """Load a conversation and verify ownership. Raises 404 on mismatch."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_conversations(
    q: Optional[str] = Query(None, description="Search in titles and message content"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
):
    """Return conversations for the current user, with optional full-text search."""
    async with async_session() as db:
        base_filter = Conversation.user_id == current_user.id

        if q and q.strip():
            pattern = f"%{q.strip()}%"
            # Subquery: conversation ids that have at least one message matching
            msg_subq = (
                select(Message.conversation_id)
                .where(Message.content.ilike(pattern))
                .distinct()
                .subquery()
            )
            search_filter = or_(
                Conversation.title.ilike(pattern),
                Conversation.id.in_(select(msg_subq.c.conversation_id)),
            )
            where_clause = base_filter & search_filter
        else:
            where_clause = base_filter

        # Total count (for pagination)
        count_result = await db.execute(
            select(func.count()).select_from(Conversation).where(where_clause)
        )
        total_count = count_result.scalar() or 0

        # Paginated results
        result = await db.execute(
            select(Conversation)
            .where(where_clause)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        convs = result.scalars().all()

    return {
        "conversations": [
            {
                "id": str(c.id),
                "title": c.title or "Conversation",
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
    }


@router.put("/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    body: RenameBody,
    current_user=Depends(get_current_user),
):
    """Rename a conversation."""
    async with async_session() as db:
        conv = await _get_owned_conversation(db, conversation_id, current_user.id)
        conv.title = body.title
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

    return {
        "id": str(conv.id),
        "title": conv.title,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user=Depends(get_current_user),
):
    """Delete a conversation and all its messages (cascade)."""
    async with async_session() as db:
        conv = await _get_owned_conversation(db, conversation_id, current_user.id)
        await db.delete(conv)
        await db.commit()

    return {"ok": True}


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    current_user=Depends(get_current_user),
):
    """Return all messages for a specific conversation."""
    async with async_session() as db:
        conv = await _get_owned_conversation(db, conversation_id, current_user.id)

        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

    return {
        "id": str(conv.id),
        "title": conv.title or "Conversation",
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    current_user=Depends(get_current_user),
):
    """Export a conversation and its messages as JSON."""
    async with async_session() as db:
        conv = await _get_owned_conversation(db, conversation_id, current_user.id)

        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

    return {
        "conversation": {
            "id": str(conv.id),
            "title": conv.title or "Conversation",
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
        },
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
