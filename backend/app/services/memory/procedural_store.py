# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/procedural_store.py
# @brief      Procedural memory — reusable tool-call sequences. V1 stub.
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Procedural store — Sprint 2.5 §2 type 3, §8 granularity.

V1 status — STUB only. The class is present so `MemoryRecallService`
(Jalon 3) and the typed-write routing (Jalon 4) can target it, but the
actual harvesting of procedures from successful missions lands in
Jalon 6 (maintenance agent).

Source of truth = SQL table `procedures` (Sprint 2.5 Jalon 1).
Qdrant collection `procedures` is the derived semantic index over the
`intent` field, used by `memory_recall(PROCEDURAL, query)`.
"""
from __future__ import annotations

import logging

from app.services.memory._base import BaseStore
from app.services.memory._constants import COLLECTION_PROCEDURES

logger = logging.getLogger(__name__)


class ProceduralStore(BaseStore):
    """Reusable how-to recipes. V1 stub — actual logic lands in Jalon 6."""

    COLLECTION = COLLECTION_PROCEDURES

    async def get_relevant(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[dict]:
        """Return procedures matching *query* by semantic similarity on intent.

        Empty list in V1 stub — no procedures stored yet. The recall path
        is wired so callers can already integrate without later refactor.
        """
        try:
            hits = await self._search_hybrid(
                COLLECTION_PROCEDURES,
                query,
                await self._infra.embed(query),
                user_id,
                limit,
                score_threshold=0.5,
                text_fields=["intent"],
                decay_lambda=0.0,
            )
            return [h.payload for h in hits]
        except Exception as exc:
            logger.debug("ProceduralStore.get_relevant returned empty: %s", exc)
            return []
