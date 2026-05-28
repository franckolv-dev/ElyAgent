# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/conversation.py
# @brief      SQLAlchemy Conversation model
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
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    # Hermes-style sticky toolset profile (Chantier 1, audit 2026-05-07).
    # NULL means « not yet decided » — at the next agent turn the chat
    # router will auto-detect it from the first user message and persist
    # the result. Once set, the same profile applies for every turn of
    # the conversation regardless of the message content. Allows the
    # model to learn a stable ~30-tool catalog rather than a shifting
    # filter that breaks the prompt cache.
    toolset_profile: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    # Composite index for the "list user's recent conversations" query,
    # which filters on user_id and orders by updated_at DESC.
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    # Composite index for the hot path in chat.py — loading the recent
    # history of a conversation ordered by time. Without this, SQLite
    # does a full scan on each message (80-150ms per chat).
    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )
