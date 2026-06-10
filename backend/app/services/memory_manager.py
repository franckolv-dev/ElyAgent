# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory_manager.py
# @brief      Legacy facade — delegates to the typed stores in
#             app/services/memory/. Kept for backward compatibility while
#             the 49 call sites are migrated to direct store usage.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Backward-compatibility facade over the typed memory stores.

Until Sprint 2.5 V1 (2026-05-21), this module was a monolithic 612-line
class handling four Qdrant collections inline. The Sprint 2.5 refactor
split it into typed stores under `app/services/memory/` — this file is
now a thin delegator that keeps the historical public surface alive:

    get_memory_manager().init_collections()
    get_memory_manager().store_constraint(rule, user_id)
    get_memory_manager().get_relevant_constraints(query, user_id, limit)
    get_memory_manager().store_memory(content, user_id, ...)
    get_memory_manager().get_relevant_memories(query, user_id, limit)
    get_memory_manager().store_interaction(user_msg, assistant_msg, ...)
    get_memory_manager().get_relevant_interactions(query, user_id, limit)
    get_memory_manager().store_preference(preference, user_id)
    get_memory_manager().get_user_preferences(user_id, limit)

New code should depend on the concrete stores directly (or, once Jalon 3
lands, on `MemoryRecallService.recall(type, query, ...)`).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.services.memory import (
    ConstraintStore,
    EpisodicStore,
    ProceduralStore,
    SemanticUserStore,
    get_memory_infra,
)
from app.services.memory._base import BaseStore
from app.services.memory._constants import (
    COLLECTION_CONSTRAINTS,
    COLLECTION_INTERACTIONS,
    COLLECTION_MEMORIES,
    COLLECTION_PREFERENCES,
    COLLECTION_PROCEDURES,
    VECTOR_DIM,
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """Legacy facade. Use the typed stores directly in new code."""

    def __init__(self) -> None:
        infra = get_memory_infra()
        self._infra = infra
        self.constraints = ConstraintStore(infra)
        self.episodic = EpisodicStore(infra)
        self.semantic = SemanticUserStore(infra)
        self.procedural = ProceduralStore(infra)

    # ── Init ────────────────────────────────────────────────────────────

    async def init_collections(self) -> None:
        """Create Qdrant collections if missing. Idempotent."""
        try:
            from qdrant_client.models import Distance, VectorParams
            client = self._infra.client
            collections_resp = await asyncio.to_thread(client.get_collections)
            existing = {c.name for c in collections_resp.collections}
            for name in (
                COLLECTION_MEMORIES,
                COLLECTION_CONSTRAINTS,
                COLLECTION_INTERACTIONS,
                COLLECTION_PREFERENCES,
                COLLECTION_PROCEDURES,
            ):
                if name not in existing:
                    await asyncio.to_thread(
                        client.create_collection,
                        name,
                        vectors_config=VectorParams(
                            size=VECTOR_DIM, distance=Distance.COSINE
                        ),
                    )
                # Index payload user_id (revue 2026-06-10 §4) — toutes les
                # recherches filtrent par user_id ; sans index keyword,
                # Qdrant scanne le payload des candidats HNSW et chaque
                # recherche ralentit pour tout le monde quand les
                # collections grossissent (×N users). Idempotent : appliqué
                # aussi aux collections déjà existantes.
                try:
                    from qdrant_client.models import PayloadSchemaType
                    await asyncio.to_thread(
                        client.create_payload_index,
                        name,
                        field_name="user_id",
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass  # déjà indexé — c'est le cas nominal après le 1er boot
            logger.info("Qdrant collections ready")
        except Exception as exc:
            logger.warning("Qdrant unavailable — memory disabled: %s", exc)

    # ── Backward-compat methods (delegations) ──────────────────────────

    async def store_constraint(self, rule: str, user_id: str) -> None:
        await self.constraints.store(rule, user_id)

    async def get_relevant_constraints(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[str]:
        return await self.constraints.get_relevant(query, user_id, limit)

    async def store_memory(
        self,
        content: str,
        user_id: str,
        conversation_id: str = "",
        extra_payload: dict | None = None,
    ) -> None:
        await self.semantic.store_fact(content, user_id, conversation_id, extra_payload)

    async def get_relevant_memories(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[str]:
        return await self.semantic.get_relevant_facts(query, user_id, limit)

    async def store_interaction(
        self,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        await self.episodic.store(user_msg, assistant_msg, user_id, conversation_id)

    async def get_relevant_interactions(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[dict]:
        return await self.episodic.get_relevant(query, user_id, limit)

    async def store_preference(self, preference: str, user_id: str) -> None:
        await self.semantic.store_preference(preference, user_id)

    async def get_user_preferences(self, user_id: str, limit: int = 10) -> list[str]:
        return await self.semantic.get_preferences(user_id, limit)

    # ── Public re-exports of pure helpers (used by tests) ──────────────

    _time_decay = staticmethod(BaseStore._time_decay)
    _keyword_score = staticmethod(BaseStore._keyword_score)


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()
