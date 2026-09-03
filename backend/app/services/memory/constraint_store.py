# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/constraint_store.py
# @brief      Security constraints — permanent rules learned from user refusals.
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Constraint store — Qdrant `security_constraints` (no decay)."""
from __future__ import annotations

import logging

from app.services.memory._base import BaseStore
from app.services.memory._constants import COLLECTION_CONSTRAINTS

logger = logging.getLogger(__name__)


class ConstraintStore(BaseStore):
    """Permanent security rules. Never decayed (λ = 0)."""

    async def store(self, rule: str, user_id: str) -> None:
        try:
            point_id = await self._infra.upsert(
                COLLECTION_CONSTRAINTS,
                await self._infra.embed(rule),
                {"rule": rule, "user_id": user_id, "priority": "high"},
            )
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(rule, user_id, COLLECTION_CONSTRAINTS, point_id)
        except Exception as exc:
            logger.warning("Failed to store constraint: %s", exc)

    async def get_relevant(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[str]:
        try:
            hits = await self._search_hybrid(
                COLLECTION_CONSTRAINTS,
                query,
                await self._infra.embed(query),
                user_id,
                limit,
                score_threshold=0.4,
                text_fields=["rule"],
                decay_lambda=0.0,
                fts_boost=0.15,
            )
            return [h.payload["rule"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch constraints: %s", exc)
            return []
