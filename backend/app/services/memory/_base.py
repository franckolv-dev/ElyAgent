# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/_base.py
# @brief      Shared scoring + hybrid search primitives for every typed store.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Base class for stores that index in Qdrant + FTS5.

Provides:
  - `_time_decay`     — accepts float Unix ts OR ISO 8601 string (regression
                        fix for the 2026-05-20 "BASE VIDE" bug).
  - `_keyword_score`  — fraction of significant query words present in text.
  - `_rerank`         — hybrid formula `(α·vec + β·kw + γ·fts) × decay`.
  - `_search_hybrid`  — full pipeline: FTS5 IDs + Qdrant ANN + rerank.

The base does not own any state itself — it composes a `MemoryInfra`
singleton passed in by every concrete store.
"""
from __future__ import annotations

import logging
import math
import time

from app.services.memory._constants import STOP_WORDS
from app.services.memory._infra import MemoryInfra

logger = logging.getLogger(__name__)


class BaseStore:
    """Common Qdrant + FTS5 hybrid-search machinery for typed memory stores."""

    def __init__(self, infra: MemoryInfra) -> None:
        self._infra = infra

    @staticmethod
    def _time_decay(created_at_ts: float | str | None, lambda_decay: float) -> float:
        """Exponential decay factor ∈ (0, 1].

        Accepts BOTH float Unix timestamps AND ISO 8601 strings. The 799
        production entries on Franck's account at the 2026-05-20 bench were
        all ISO strings — without the str→float normalisation here, every
        `memory_search` raised `unsupported operand type(s) for -: 'float'
        and 'str'` and returned an empty result (caught silently by the
        caller's broad `except`, so the bug surfaced as the agent saying
        "BASE VIDE" while Qdrant held 799 entries).

        Returns 1.0 (no decay applied) on parse failure — better than
        crashing the whole search over one malformed payload.
        """
        if created_at_ts is None or lambda_decay == 0.0:
            return 1.0
        if isinstance(created_at_ts, str):
            try:
                from datetime import datetime
                created_at_ts = datetime.fromisoformat(
                    created_at_ts.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                return 1.0
        age_days = max(0.0, (time.time() - created_at_ts) / 86400.0)
        return math.exp(-lambda_decay * age_days)

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Fraction of significant query words present in *text*, in [0, 1]."""
        words = {
            w.strip(".,!?;:\"'()[]")
            for w in query.lower().split()
            if len(w.strip(".,!?;:\"'()[]")) > 2
        } - STOP_WORDS
        if not words:
            return 0.0
        text_lower = text.lower()
        matches = sum(1 for w in words if w in text_lower)
        return matches / len(words)

    def _rerank(
        self,
        candidates: list,
        query: str,
        text_fields: list[str],
        fts_matches: set[str],
        decay_lambda: float,
        alpha: float,
        beta: float,
        fts_boost: float,
        limit: int,
    ) -> list:
        scored: list[tuple[float, object]] = []
        for hit in candidates:
            text = " ".join(str(hit.payload.get(f, "")) for f in text_fields)
            kw = self._keyword_score(query, text)
            decay = self._time_decay(hit.payload.get("created_at"), decay_lambda)
            fts = fts_boost if str(hit.id) in fts_matches else 0.0
            score = (alpha * hit.score + beta * kw + fts) * decay
            scored.append((score, hit))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in scored[:limit]]

    async def _search_hybrid(
        self,
        collection: str,
        query: str,
        vector: list[float],
        user_id: str,
        limit: int,
        score_threshold: float,
        text_fields: list[str],
        decay_lambda: float = 0.02,
        alpha: float = 0.65,
        beta: float = 0.25,
        fts_boost: float = 0.10,
    ) -> list:
        from app.services.fts_store import get_fts_store
        fts_matches = set(
            await get_fts_store().search(
                query, user_id, collection, limit=limit * 4
            )
        )
        candidates = await self._infra.qdrant_candidates(
            collection, vector, user_id, limit, score_threshold
        )
        if not candidates:
            return []
        return self._rerank(
            candidates, query, text_fields,
            fts_matches, decay_lambda, alpha, beta, fts_boost, limit,
        )
