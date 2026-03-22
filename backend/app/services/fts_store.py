"""SQLite FTS5 full-text search index for memory content.

Complements Qdrant's vector search with exact keyword / prefix matching.
Stored in the same SQLite file as the main application DB.

Architecture
------------
- One virtual FTS5 table ``memory_fts`` shared across all collections.
- Each row stores: the text content, the user_id, which Qdrant collection
  it belongs to, and the Qdrant point UUID (``qdrant_id``).
- The ``qdrant_id`` is the join key used by MemoryManager to apply an FTS
  boost to vector search results without a second Qdrant round-trip.

Query strategy
--------------
User free-text is converted to a safe FTS5 expression:
  - Punctuation stripped, stop-words removed
  - Each remaining word becomes a prefix-match OR term:  ``"word"*``
  - Limited to 10 terms to keep queries fast
  - Any syntax error falls back to empty results (never raises)
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    text,
    user_id     UNINDEXED,
    collection  UNINDEXED,
    qdrant_id   UNINDEXED,
    tokenize    = 'unicode61 remove_diacritics 1'
)
"""

# Common French + English stop-words — short, high-frequency words that add
# noise to keyword matching without contributing to meaning.
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
    """Extract filesystem path from the SQLAlchemy async database URL.

    ``sqlite+aiosqlite:///./cyberentity.db``  →  ``./cyberentity.db``
    """
    url = get_settings().database_url
    return url.split("sqlite+aiosqlite:///")[-1]


def _build_fts_query(query: str) -> str:
    """Convert free-text into a valid FTS5 OR-expression with prefix matching.

    Returns an empty string when no meaningful terms remain (caller should
    skip the FTS search in that case).
    """
    # Strip non-word characters, keep accented letters
    words = re.sub(
        r"[^\w\sàâäéèêëîïôùûüç]", " ", query.lower(), flags=re.UNICODE
    ).split()
    # Filter stop-words and very short tokens
    words = [w for w in words if len(w) > 2 and w not in _STOP]
    if not words:
        return ""
    # Prefix-match each term; FTS5 ``"word"*`` matches "word", "words", etc.
    return " OR ".join(f'"{w}"*' for w in words[:10])


class FTSStore:
    """Async SQLite FTS5 index over memory text content."""

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def init(self) -> None:
        """Create the FTS5 virtual table if it does not already exist."""
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await db.execute(_CREATE_TABLE)
                await db.commit()
            logger.info("FTS5 memory index ready")
        except Exception as exc:
            logger.warning("FTS5 init failed — text search disabled: %s", exc)

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    async def store(
        self,
        text: str,
        user_id: str,
        collection: str,
        qdrant_id: str,
    ) -> None:
        """Index a memory item so it can be retrieved by keyword search."""
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await db.execute(
                    "INSERT INTO memory_fts(text, user_id, collection, qdrant_id)"
                    " VALUES (?, ?, ?, ?)",
                    (text, user_id, collection, qdrant_id),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("FTS store failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    async def search(
        self,
        query: str,
        user_id: str,
        collection: str,
        limit: int = 20,
    ) -> list[str]:
        """Return Qdrant point IDs whose indexed text matches *query*.

        Results are ordered by FTS5 BM25 rank (best match first).
        Returns an empty list on any error so callers degrade gracefully.
        """
        fts_query = _build_fts_query(query)
        if not fts_query:
            return []
        try:
            async with aiosqlite.connect(_db_path()) as db:
                cursor = await db.execute(
                    """
                    SELECT   qdrant_id
                    FROM     memory_fts
                    WHERE    memory_fts MATCH ?
                      AND    user_id    = ?
                      AND    collection = ?
                    ORDER BY rank
                    LIMIT    ?
                    """,
                    (fts_query, user_id, collection, limit),
                )
                rows = await cursor.fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            # FTS5 syntax errors (e.g. bare special chars) are not fatal
            logger.debug("FTS search error (ignored): %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Maintenance                                                          #
    # ------------------------------------------------------------------ #

    async def delete_user_data(self, user_id: str) -> None:
        """Remove all FTS entries for a given user (GDPR / account deletion)."""
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await db.execute(
                    "DELETE FROM memory_fts WHERE user_id = ?", (user_id,)
                )
                await db.commit()
            logger.info("FTS data deleted for user %s", user_id)
        except Exception as exc:
            logger.warning("FTS delete_user_data failed: %s", exc)


@lru_cache(maxsize=1)
def get_fts_store() -> FTSStore:
    return FTSStore()
