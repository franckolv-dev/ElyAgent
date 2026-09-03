# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/messages_fts_store.py
# @brief      SQLite FTS5 index over conversation messages (Sprint 1).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Cross-conversation full-text search over the user's message history.

Sister service to ``fts_store.py``, but with a different scope:

  - ``fts_store.py`` indexes **memory items** (knowledge chunks, facts
    extracted by the background extractor) — the agent's "long-term
    memory" so to speak.
  - ``messages_fts_store.py`` (this file) indexes the **raw messages**
    of every conversation — the agent's "episodic memory" of what was
    literally said, when, in which conversation.

Why a separate table
--------------------
Sharing ``memory_fts`` would have two drawbacks:
  - Mixing semantic granularities (a fact like "Franck uses pytest"
    vs. a literal message "I'm running pytest now") confuses BM25
    ranking, polluting both kinds of search.
  - User-deletable conversations should also remove their messages
    from the FTS index, but the same operation on a shared table
    would risk deleting memory items.

Schema
------
    messages_fts (
        text         (indexed),
        message_id   UNINDEXED,   -- UUID of the message
        conversation_id UNINDEXED,
        user_id      UNINDEXED,
        role         UNINDEXED,   -- 'user' | 'assistant' (we skip 'system')
        created_at_ts UNINDEXED,  -- epoch seconds for ORDER BY in callers
        tokenize = 'unicode61 remove_diacritics 1'
    )

The tokenizer is the same as ``memory_fts``: Unicode-aware, accent-
folding, so a search for "creneaux" matches "créneaux". The
``remove_diacritics 1`` setting also folds combined-form vs.
decomposed-form Unicode (NFC vs NFD), which matters when the input
comes from copy-pasted French web content.

Hot path expected from session_search.py
----------------------------------------
1. ``search(query, user_id, limit=N)`` →  list of (conversation_id, message_id, snippet, rank)
2. Caller groups by conversation_id, sorts by best rank, keeps top K convs.
3. For each kept conv, caller loads the surrounding ±100k chars from
   the main ``messages`` table to feed a cheap LLM summariser.

Failure mode
------------
All operations are best-effort and never raise. If FTS5 is unavailable
(broken SQLite build, syntax error in user query), the search returns
an empty list — the agent can fall back to "I don't remember this".
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

import aiosqlite  # noqa: F401  (kept: Row/static typing helpers)
from app.services.sqlite_aio import connect as _connect

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Schema ───────────────────────────────────────────────────────────
_CREATE_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    message_id      UNINDEXED,
    conversation_id UNINDEXED,
    user_id         UNINDEXED,
    role            UNINDEXED,
    created_at_ts   UNINDEXED,
    tokenize        = 'unicode61 remove_diacritics 1'
)
"""

# Common French + English stop-words (mirrors fts_store.py). Kept
# in-module so both stores can diverge independently if needed.
_STOP = frozenset({
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "à", "au",
    "aux", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "me",
    "te", "se", "que", "qui", "quoi", "où", "comment", "quand", "pourquoi",
    "ce", "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa", "pas", "ne",
    "plus", "par", "sur", "sous", "dans", "avec", "pour", "sans", "est",
    "the", "a", "an", "of", "in", "is", "it", "to", "for", "on", "with",
    "are", "was", "were", "be", "been", "have", "has", "had", "do", "did",
})


def _db_path() -> str:
    """Extract the filesystem path of the application SQLite DB."""
    url = get_settings().database_url
    return url.split("sqlite+aiosqlite:///")[-1]


def _build_fts_query(query: str) -> str:
    """Convert free-text into a safe FTS5 OR-expression with prefix match.

    Returns an empty string when nothing meaningful remains — callers
    must skip the SQL execution in that case (FTS5 rejects empty
    expressions).
    """
    words = re.sub(
        r"[^\w\sàâäéèêëîïôùûüç]", " ", query.lower(), flags=re.UNICODE
    ).split()
    words = [w for w in words if len(w) > 2 and w not in _STOP]
    if not words:
        return ""
    return " OR ".join(f'"{w}"*' for w in words[:10])


# ── Public dataclass-like dict shape returned by search() ─────────────
# Using a plain dict (not a TypedDict) for ease of JSON-serialisation
# in the tool layer. Documented here so callers know what to expect:
#
#   {
#     "message_id":      str,
#     "conversation_id": str,
#     "role":            "user" | "assistant",
#     "created_at_ts":   int,   # epoch seconds
#     "snippet":         str,   # message text, truncated to ~400 chars
#     "rank":            float, # FTS5 BM25 score, lower = better match
#   }


class MessagesFTSStore:
    """Async SQLite FTS5 index over the ``messages`` table."""

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def init(self) -> None:
        """Create the FTS5 virtual table if it does not already exist.

        Safe to call repeatedly — `CREATE VIRTUAL TABLE IF NOT EXISTS`
        is a no-op when the table is already there.
        """
        try:
            async with _connect(_db_path()) as db:
                await db.execute(_CREATE_TABLE)
                await db.commit()
            logger.info("messages_fts index ready")
        except Exception as exc:
            logger.warning("messages_fts init failed — recall disabled: %s", exc)

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    async def index_message(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        role: str,
        text: str,
        created_at_ts: int,
    ) -> None:
        """Index a single message. Best-effort, never raises.

        ``role`` of 'system' is silently skipped — system prompts are
        not user-visible content and would only pollute search results.
        Empty content (e.g. assistant message that's only tool_calls)
        is also skipped.
        """
        if role == "system":
            return
        if not text or not text.strip():
            return
        try:
            async with _connect(_db_path()) as db:
                await db.execute(
                    "INSERT INTO messages_fts"
                    " (text, message_id, conversation_id, user_id, role, created_at_ts)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (text, message_id, conversation_id, user_id, role, created_at_ts),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("messages_fts index_message failed (id=%s): %s", message_id, exc)

    async def index_batch(self, rows: list[dict]) -> int:
        """Bulk-index a list of message dicts. Returns count of inserted rows.

        Used by the bootstrap script to backfill the FTS index for
        messages that existed before this feature shipped. ``rows`` is
        a list of dicts with the same keys as ``index_message``'s args.
        """
        valid = [
            r for r in rows
            if r.get("role") != "system" and (r.get("text") or "").strip()
        ]
        if not valid:
            return 0
        try:
            async with _connect(_db_path()) as db:
                await db.executemany(
                    "INSERT INTO messages_fts"
                    " (text, message_id, conversation_id, user_id, role, created_at_ts)"
                    " VALUES (:text, :message_id, :conversation_id, :user_id, :role, :created_at_ts)",
                    valid,
                )
                await db.commit()
            return len(valid)
        except Exception as exc:
            logger.warning("messages_fts index_batch failed: %s", exc)
            return 0

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 50,
        snippet_chars: int = 400,
    ) -> list[dict]:
        """Full-text search over the user's messages.

        Args:
            query:         free-text user query (will be tokenised + de-stopworded)
            user_id:       scope (each user only sees their own messages)
            limit:         maximum number of matched messages to return
                           (group-by-conversation happens caller-side)
            snippet_chars: truncate each message's text to this length in
                           the returned snippet (keeps memory bounded
                           when matching a 50k-char message)

        Returns: list of dicts as documented at module-level. Empty list
                 on any error or when the query has no usable terms.
        """
        fts_query = _build_fts_query(query)
        if not fts_query:
            return []
        try:
            async with _connect(_db_path()) as db:
                cursor = await db.execute(
                    """
                    SELECT   message_id, conversation_id, role,
                             created_at_ts, substr(text, 1, ?) AS snippet,
                             rank
                    FROM     messages_fts
                    WHERE    messages_fts MATCH ?
                      AND    user_id = ?
                    ORDER BY rank
                    LIMIT    ?
                    """,
                    (snippet_chars, fts_query, user_id, limit),
                )
                rows = await cursor.fetchall()
            return [
                {
                    "message_id": r[0],
                    "conversation_id": r[1],
                    "role": r[2],
                    "created_at_ts": r[3],
                    "snippet": r[4],
                    "rank": r[5],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.debug("messages_fts search error (ignored): %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Maintenance                                                          #
    # ------------------------------------------------------------------ #

    async def delete_conversation(self, conversation_id: str) -> None:
        """Remove all FTS entries for a deleted conversation.

        Called from the conversation-deletion path so the user's "I
        deleted that conversation" intent fully propagates.
        """
        try:
            async with _connect(_db_path()) as db:
                await db.execute(
                    "DELETE FROM messages_fts WHERE conversation_id = ?",
                    (conversation_id,),
                )
                await db.commit()
        except Exception as exc:
            logger.warning(
                "messages_fts delete_conversation failed (conv=%s): %s",
                conversation_id, exc,
            )

    async def delete_user_data(self, user_id: str) -> None:
        """Remove all FTS entries for a user (GDPR / account deletion)."""
        try:
            async with _connect(_db_path()) as db:
                await db.execute(
                    "DELETE FROM messages_fts WHERE user_id = ?", (user_id,)
                )
                await db.commit()
            logger.info("messages_fts data deleted for user %s", user_id)
        except Exception as exc:
            logger.warning("messages_fts delete_user_data failed: %s", exc)

    async def count_for_user(self, user_id: str) -> int:
        """Return the number of indexed messages for diagnostics."""
        try:
            async with _connect(_db_path()) as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM messages_fts WHERE user_id = ?",
                    (user_id,),
                )
                row = await cursor.fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0


@lru_cache(maxsize=1)
def get_messages_fts_store() -> MessagesFTSStore:
    """Singleton accessor used by services and tools."""
    return MessagesFTSStore()
