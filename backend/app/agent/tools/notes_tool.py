# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/notes_tool.py
# @brief      Notes / Presse-papier tools — create, read, update, delete personal notes.
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
"""Notes / Presse-papier tools — create, read, update, delete personal notes."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg
from sqlalchemy import select, or_

from app.database import async_session
from app.models.note import Note


def _fmt(note: Note) -> str:
    tags = f"  [tags: {note.tags}]" if note.tags else ""
    pin = " 📌" if note.pinned else ""
    return (
        f"ID: {note.id}\n"
        f"Titre: {note.title}{pin}{tags}\n"
        f"Contenu: {note.content}\n"
        f"Créé: {note.created_at.strftime('%d/%m/%Y %H:%M')}"
    )


@tool
async def notes_create(
    title: str,
    content: str,
    tags: str = "",
    pinned: bool = False,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new personal note or clipboard snippet.

    Args:
        title: Short title for the note
        content: Full content of the note
        tags: Optional comma-separated tags (e.g. 'idée,projet,urgent')
        pinned: Whether to pin this note at the top
    """
    note = Note(
        user_id=user_id,
        title=title,
        content=content,
        tags=tags or None,
        pinned=pinned,
    )
    async with async_session() as db:
        db.add(note)
        await db.commit()
        await db.refresh(note)

    return f"Note créée ✅\n{_fmt(note)}"


@tool
async def notes_list(
    tag: str = "",
    pinned_only: bool = False,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all personal notes, optionally filtered by tag or pinned status.

    Args:
        tag: Filter by tag (leave empty to list all)
        pinned_only: If true, return only pinned notes
    """
    async with async_session() as db:
        q = select(Note).where(Note.user_id == user_id)
        if pinned_only:
            q = q.where(Note.pinned.is_(True))
        if tag:
            q = q.where(Note.tags.contains(tag))
        q = q.order_by(Note.pinned.desc(), Note.updated_at.desc())
        result = await db.execute(q)
        notes = result.scalars().all()

    if not notes:
        return "Aucune note trouvée."

    summaries = []
    for n in notes:
        pin = " 📌" if n.pinned else ""
        preview = n.content[:80].replace("\n", " ")
        if len(n.content) > 80:
            preview += "…"
        summaries.append(f"• [{n.id[:8]}] {n.title}{pin} — {preview}")

    return f"{len(notes)} note(s) :\n" + "\n".join(summaries)


@tool
async def notes_read(
    note_id: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the full content of a note by its ID.

    Args:
        note_id: The note ID (from notes_list — can be partial, first 8 chars)
    """
    async with async_session() as db:
        result = await db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(Note.id == note_id, Note.id.startswith(note_id)),
            )
        )
        note = result.scalars().first()

    if not note:
        return f"Note introuvable (ID: {note_id})."

    return _fmt(note)


@tool
async def notes_update(
    note_id: str,
    title: str = "",
    content: str = "",
    tags: str = "",
    pinned: bool | None = None,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update an existing note.

    Only the fields you provide will be updated (leave blank to keep current value).

    Args:
        note_id: The note ID to update (can be partial, first 8 chars)
        title: New title (leave empty to keep current)
        content: New content (leave empty to keep current)
        tags: New comma-separated tags (leave empty to keep current)
        pinned: Pin or unpin the note (omit to keep current)
    """
    async with async_session() as db:
        result = await db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(Note.id == note_id, Note.id.startswith(note_id)),
            )
        )
        note = result.scalars().first()
        if not note:
            return f"Note introuvable (ID: {note_id})."

        if title:
            note.title = title
        if content:
            note.content = content
        if tags:
            note.tags = tags
        if pinned is not None:
            note.pinned = pinned

        await db.commit()
        await db.refresh(note)

    return f"Note mise à jour ✅\n{_fmt(note)}"


@tool
async def notes_delete(
    note_id: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Delete a note permanently.

    Args:
        note_id: The note ID to delete (can be partial, first 8 chars)
    """
    async with async_session() as db:
        result = await db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(Note.id == note_id, Note.id.startswith(note_id)),
            )
        )
        note = result.scalars().first()
        if not note:
            return f"Note introuvable (ID: {note_id})."

        title = note.title
        await db.delete(note)
        await db.commit()

    return f"Note « {title} » supprimée."


@tool
async def notes_search(
    query: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search notes by keyword (searches title, content and tags).

    Args:
        query: Search keyword(s)
    """
    async with async_session() as db:
        result = await db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(
                    Note.title.ilike(f"%{query}%"),
                    Note.content.ilike(f"%{query}%"),
                    Note.tags.ilike(f"%{query}%"),
                ),
            ).order_by(Note.pinned.desc(), Note.updated_at.desc())
        )
        notes = result.scalars().all()

    if not notes:
        return f"Aucune note trouvée pour « {query} »."

    summaries = []
    for n in notes:
        pin = " 📌" if n.pinned else ""
        preview = n.content[:80].replace("\n", " ")
        if len(n.content) > 80:
            preview += "…"
        summaries.append(f"• [{n.id[:8]}] {n.title}{pin} — {preview}")

    return f"{len(notes)} résultat(s) pour « {query} » :\n" + "\n".join(summaries)
