# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/episodic_store.py
# @brief      Episodic memory — past Q&A pairs (interactions collection).
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Episodic store — past conversation exchanges (interactions collection).

Stores complete Q&A pairs for semantic retrieval of "what was discussed
when". Decay λ = 0.05 → ~14-day half-life (recency matters here).

Note: In Sprint 2.5 §2, episodic memory also covers the `messages` SQL
table with FTS5 — that integration is added in Jalon 3 when the
`memory_recall` API is wired. For now this store wraps the legacy
`interactions` collection 1:1.
"""
from __future__ import annotations

import logging

from app.services.memory._base import BaseStore
from app.services.memory._constants import COLLECTION_INTERACTIONS

logger = logging.getLogger(__name__)


class EpisodicStore(BaseStore):
    """Past Q&A pairs — semantic retrieval over recent exchanges."""

    async def store(
        self,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        try:
            content = f"Question: {user_msg}\nRéponse: {assistant_msg}"
            point_id = await self._infra.upsert(
                COLLECTION_INTERACTIONS,
                await self._infra.embed(user_msg),
                {
                    "user_message": user_msg,
                    "assistant_message": assistant_msg,
                    "content": content,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                },
            )
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(content, user_id, COLLECTION_INTERACTIONS, point_id)
        except Exception as exc:
            logger.warning("Failed to store interaction: %s", exc)

    async def get_relevant(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[dict]:
        try:
            hits = await self._search_hybrid(
                COLLECTION_INTERACTIONS,
                query,
                await self._infra.embed(query),
                user_id,
                limit,
                score_threshold=0.5,
                text_fields=["user_message", "assistant_message"],
                decay_lambda=0.05,
            )
            return [h.payload for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch interactions: %s", exc)
            return []
