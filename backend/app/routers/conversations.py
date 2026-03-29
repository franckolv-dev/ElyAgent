"""Conversations API — list recent conversations and load message history."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.conversation import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    limit: int = 15,
    current_user=Depends(get_current_user),
):
    """Return the most recent conversations for the current user."""
    async with async_session() as db:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        convs = result.scalars().all()

    return [
        {
            "id": str(c.id),
            "title": c.title or "Conversation",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in convs
    ]


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    current_user=Depends(get_current_user),
):
    """Return all messages for a specific conversation."""
    async with async_session() as db:
        # Verify ownership
        conv = await db.get(Conversation, conversation_id)
        if not conv or conv.user_id != current_user.id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Conversation not found")

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
