# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/semantic_user_store.py
# @brief      Stable user knowledge — facts + preferences + communication style.
# @license    MIT
# @version    1.3.0
# =============================================================================
"""Semantic-user store — stable facts about the user.

Currently wraps TWO Qdrant collections that both contain user knowledge:

  - `memories` (λ = 0.01, ~69-day half-life)  — episodic-ish facts about
    the user's life ("user works on project X", "user's wife uses iPhone")
  - `user_profile` (no decay) — communication style + recurring habits
    ("be concise", "respond in French")

Sprint 2.5 §6 says SQL `user_profiles` is the canonical source of truth
and the Qdrant collections are the derived semantic index. The merge of
the two collections + reconciliation with SQL happens in V2 (Sprint 2.8).
For now this store keeps them separate, mirroring the legacy
`MemoryManager` behaviour 1:1.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.services.memory._base import BaseStore
from app.services.memory._constants import COLLECTION_MEMORIES, COLLECTION_PREFERENCES

logger = logging.getLogger(__name__)


class SemanticUserStore(BaseStore):
    """Stable knowledge about the user — facts (memories) + preferences."""

    # ── Facts (`memories` collection — λ=0.01) ──────────────────────────

    async def store_fact(
        self,
        content: str,
        user_id: str,
        conversation_id: str = "",
        extra_payload: dict | None = None,
    ) -> None:
        try:
            payload: dict = {
                "content": content,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if extra_payload:
                for k, v in extra_payload.items():
                    if k not in payload:
                        payload[k] = v
            point_id = await self._infra.upsert(
                COLLECTION_MEMORIES,
                await self._infra.embed(content),
                payload,
            )
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(content, user_id, COLLECTION_MEMORIES, point_id)
        except Exception as exc:
            logger.warning("Failed to store fact: %s", exc)

    async def get_relevant_facts(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[str]:
        try:
            hits = await self._search_hybrid(
                COLLECTION_MEMORIES,
                query,
                await self._infra.embed(query),
                user_id,
                limit,
                score_threshold=0.45,
                text_fields=["content"],
                decay_lambda=0.01,
            )
            return [h.payload["content"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch memories: %s", exc)
            return []

    # ── Preferences (`user_profile` collection — no decay, dedup) ──────

    async def store_preference(self, preference: str, user_id: str) -> None:
        """Store a preference. Dedup near-identical via cosine ≥ 0.88."""
        try:
            vector = await self._infra.embed(preference)
            from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
            client = self._infra.client
            candidates = await asyncio.to_thread(
                client.query_points,
                collection_name=COLLECTION_PREFERENCES,
                query=vector,
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=3,
                score_threshold=0.88,
                with_payload=True,
            )
            if candidates.points:
                existing = candidates.points[0]
                point_id = str(existing.id)
                await asyncio.to_thread(
                    client.upsert,
                    collection_name=COLLECTION_PREFERENCES,
                    points=[PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "content": preference,
                            "user_id": user_id,
                            "created_at": existing.payload.get("created_at", time.time()),
                            "updated_at": time.time(),
                        },
                    )],
                )
                logger.debug("Updated existing preference (dedup): %s", preference[:60])
            else:
                point_id = await self._infra.upsert(
                    COLLECTION_PREFERENCES,
                    vector,
                    {"content": preference, "user_id": user_id},
                )
                logger.debug("Stored new preference: %s", preference[:60])

            from app.services.fts_store import get_fts_store
            await get_fts_store().store(
                preference, user_id, COLLECTION_PREFERENCES, point_id
            )
        except Exception as exc:
            logger.warning("Failed to store preference: %s", exc)

    async def get_preferences(self, user_id: str, limit: int = 10) -> list[str]:
        """Scroll-fetch all preferences for the user (no semantic query)."""
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            result = await asyncio.to_thread(
                self._infra.client.scroll,
                collection_name=COLLECTION_PREFERENCES,
                scroll_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=limit,
                with_payload=True,
            )
            return [p.payload["content"] for p in result[0]]
        except Exception as exc:
            logger.warning("Failed to fetch preferences: %s", exc)
            return []
