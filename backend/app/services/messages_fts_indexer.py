# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/messages_fts_indexer.py
# @brief      SQLAlchemy event hook: auto-index every new Message into
#             messages_fts. Sprint 1 — Memory recall.
#
# @license    Elastic License 2.0
# =============================================================================
"""Auto-indexing hook for Sprint 1 — Memory recall.

Why an event listener rather than calling ``index_message`` from each
of chat.py / voice.py / channels/*.py / etc.?

  - **DRY**: a single source of truth for what "a new message exists"
    means.
  - **Future-proof**: any new code path that creates ``Message`` rows
    inherits the indexing for free, without the author having to
    remember to call the indexer.
  - **Decoupled**: the FTS index is a *secondary* artifact of the
    conversation history. Coupling its creation to every call site
    would scatter the same boilerplate across the codebase.

How it works
------------
SQLAlchemy fires an ``after_insert`` event on the ``Message`` mapper
whenever a flush sends a new row to the database. We schedule an
asyncio task to do the FTS insert in the background — fire-and-forget.
If indexing fails (FTS5 unavailable, DB locked, etc.) we log and move
on; the main conversation flow is never blocked.

User_id resolution
------------------
``Message`` doesn't carry ``user_id`` directly — it has
``conversation_id``, and the conversation has the user. We do a small
SQLite read inside the indexing task to fetch the user_id. Cheap (the
index lookup is in cache after the first hit per conversation) and
avoids changing the Message schema.

Bootstrap considerations
------------------------
This hook only catches *new* messages from the moment it's wired up.
Existing messages in the DB need a one-time backfill — see
``scripts/backfill_messages_fts.py``.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import event

from app.models.conversation import Message
from app.services.background_tasks import spawn
from app.services.messages_fts_store import get_messages_fts_store

logger = logging.getLogger(__name__)


def _schedule_index(message_id: str, conversation_id: str, role: str,
                    text: str, created_at_ts: int) -> None:
    """Fire-and-forget the async indexing.

    Called from the synchronous ``after_insert`` event. On a running loop we
    hand the coroutine to ``background_tasks.spawn``; otherwise we fall back
    to a new event loop in a thread (covers the rare case of a Message being
    created during synchronous bootstrap).

    ⚠️ (audit 02/09) ce site était un `loop.create_task` NU. La boucle ne
    garde qu'une référence FAIBLE sur la tâche : sous pression du
    ramasse-miettes, le message n'entrait jamais dans l'index et « tu te
    souviens de… » ne pouvait plus le retrouver. C'est le trou que la
    docstring de `background_tasks` cite comme motif d'existence du module ;
    il y avait survécu.
    """
    try:
        asyncio.get_running_loop()
        spawn(
            _do_index(message_id, conversation_id, role, text, created_at_ts),
            label="messages_fts.index",
        )
    except RuntimeError:
        # No running loop — bootstrap path. Use a separate thread with
        # its own loop so we don't block the caller and the index still
        # gets populated. Rare in practice.
        import threading
        threading.Thread(
            target=lambda: asyncio.run(_do_index(
                message_id, conversation_id, role, text, created_at_ts,
            )),
            daemon=True,
        ).start()


async def _do_index(message_id: str, conversation_id: str, role: str,
                    text: str, created_at_ts: int) -> None:
    """Resolve the conversation's user_id and index the message."""
    # Skip empties early to save a DB round-trip
    if role == "system" or not text or not text.strip():
        return

    # Resolve user_id via the conversation. Done inside its own async
    # session so we don't pollute the caller's transaction.
    user_id = await _resolve_user_id(conversation_id)
    if not user_id:
        logger.debug(
            "messages_fts: skipping message %s — no user_id resolvable "
            "(conv=%s)", message_id, conversation_id,
        )
        return

    await get_messages_fts_store().index_message(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        text=text,
        created_at_ts=created_at_ts,
    )


async def _resolve_user_id(conversation_id: str) -> str | None:
    """Look up the user_id for a given conversation. Cached for speed."""
    # We do a small read using the same DB the rest of the app uses.
    # Going through SQLAlchemy here would risk recursion (we'd see our
    # own after_insert fire again on any related INSERT). Plain
    # aiosqlite is simpler and faster for this single lookup.
    import aiosqlite
    from app.config import get_settings
    db_url = get_settings().database_url
    db_path = db_url.split("sqlite+aiosqlite:///")[-1]
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT user_id FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.debug("messages_fts: user_id lookup failed: %s", exc)
        return None


# ── Wire the event ────────────────────────────────────────────────────
@event.listens_for(Message, "after_insert")
def _on_message_insert(_mapper, _connection, target: Message) -> None:
    """SQLAlchemy hook: fires after every INSERT into the messages table.

    We extract the message details synchronously (they're already in
    memory on the Message instance), then hand off to async work via
    ``_schedule_index``. The DB transaction is unaffected.
    """
    try:
        # Convert datetime to epoch seconds — easier to ORDER BY in SQL
        # and works regardless of timezone tagging.
        created_ts = int(target.created_at.timestamp()) if target.created_at else 0
        _schedule_index(
            message_id=str(target.id),
            conversation_id=str(target.conversation_id),
            role=str(target.role or ""),
            text=str(target.content or ""),
            created_at_ts=created_ts,
        )
    except Exception as exc:
        # Never let the FTS hook break the main insert
        logger.warning("messages_fts after_insert hook failed: %s", exc)


def install_indexer() -> None:
    """Idempotent installer — importing this module is enough.

    The ``@event.listens_for`` decorator above already registers the
    hook at import time. This function exists as an explicit
    entry-point to call from app bootstrap, so the import is visible
    in the startup log.
    """
    logger.info("messages_fts auto-indexer hook installed")
