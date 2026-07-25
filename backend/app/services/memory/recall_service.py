# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/recall_service.py
# @brief      MemoryRecallService — unified `recall(type, query)` API over
#             the 5 typed stores.
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Unified `memory_recall(type, query)` — Sprint 2.5 §3.

The public API of the typed memory subpackage. Every caller (LangChain
tool, voice loop, supervisor) goes through this service rather than
poking the underlying stores directly. This is the seam that lets us
change physical storage later (e.g. Qdrant→pgvector) without breaking
callers.

`type=AUTO` fans out to all relevant stores in parallel and merges
results by score. `type=ERROR` returns empty in V1 (write-only — read
path lands in Sprint 3.7).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.services.memory._infra import get_memory_infra
from app.services.memory.constraint_store import ConstraintStore
from app.services.memory.episodic_store import EpisodicStore
from app.services.memory.semantic_user_store import SemanticUserStore
from app.services.memory.types import MemoryHit, MemoryType

logger = logging.getLogger(__name__)


class UnreadableMemoryType(RuntimeError):
    """Ce type de mémoire n'a aucune lecture implémentée.

    Distinct d'un « aucun résultat » : la nuance compte pour le modèle. Une
    liste vide se lit « je n'ai rien en mémoire là-dessus » — une affirmation
    sur le monde. Cette exception dit « cette mémoire n'est pas consultable »
    — une affirmation sur l'outil. Confondre les deux, c'est fabriquer une
    façade, ce que la boucle d'auto-diagnostic cherche justement à détecter.
    """

    def __init__(self, memory_type: MemoryType) -> None:
        self.memory_type = memory_type
        super().__init__(f"memory type {memory_type.value!r} is not readable")


# PROCEDURAL : le magasin était un stub sans aucune voie d'écriture (retiré
# en V0-5). ERROR : écriture seule — les erreurs partent en failure_cases,
# rien ne les relit.
_UNREADABLE_TYPES = frozenset({MemoryType.PROCEDURAL, MemoryType.ERROR})


class MemoryRecallService:
    """Unified entry-point for typed memory recall."""

    def __init__(self) -> None:
        infra = get_memory_infra()
        self.constraints = ConstraintStore(infra)
        self.episodic = EpisodicStore(infra)
        self.semantic = SemanticUserStore(infra)

    async def recall(
        self,
        memory_type: MemoryType | str,
        query: str,
        user_id: str,
        limit: int = 5,
        filter: dict | None = None,  # reserved for V2 — currently ignored
    ) -> list[MemoryHit]:
        """Recall memories of `memory_type` matching `query` for `user_id`.

        Always returns a list (possibly empty). Never raises — recall is
        best-effort, callers should not need defensive try/except.
        """
        if not user_id:
            logger.warning("memory_recall refused: empty user_id")
            return []
        if not query or not query.strip():
            return []

        mt = MemoryType.parse(memory_type)
        # V0-5 — deux types n'ont AUCUNE lecture derrière eux :
        #   PROCEDURAL : le magasin était un stub sans voie d'écriture ;
        #   ERROR      : écriture seule (les erreurs vont en failure_cases).
        # Levé AVANT le try : rendre [] ferait lire au modèle « aucune
        # procédure connue » / « je n'ai jamais échoué là-dessus » — une
        # affirmation fausse présentée comme un fait.
        if mt in _UNREADABLE_TYPES:
            raise UnreadableMemoryType(mt)
        try:
            if mt == MemoryType.AUTO:
                return await self._recall_auto(query, user_id, limit)
            if mt == MemoryType.EPISODIC:
                return await self._recall_episodic(query, user_id, limit)
            if mt == MemoryType.SEMANTIC_USER:
                return await self._recall_semantic_user(query, user_id, limit)
            if mt == MemoryType.CONSTRAINT:
                return await self._recall_constraint(query, user_id, limit)
        except Exception as exc:
            logger.warning(
                "MemoryRecallService.recall(%s) failed: %s — returning []",
                mt.value, exc,
            )
            return []
        return []

    # ── Per-type recall implementations ────────────────────────────────

    async def _recall_episodic(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        rows = await self.episodic.get_relevant(query, user_id, limit)
        out: list[MemoryHit] = []
        for r in rows:
            content = r.get("content") or r.get("user_message") or ""
            out.append(MemoryHit(
                type=MemoryType.EPISODIC,
                content=content,
                # episodic.get_relevant doesn't currently surface the
                # hybrid score — placeholder 1.0 here is fine for V1.
                score=1.0,
                metadata={
                    "user_message": r.get("user_message"),
                    "assistant_message": r.get("assistant_message"),
                    "conversation_id": r.get("conversation_id"),
                },
                created_at=str(r.get("created_at")) if r.get("created_at") else None,
            ))
        return out

    async def _recall_semantic_user(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        facts, prefs = await asyncio.gather(
            self.semantic.get_relevant_facts(query, user_id, limit),
            self.semantic.get_preferences(user_id, limit),
        )
        out: list[MemoryHit] = []
        for content in facts:
            out.append(MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content=content,
                score=1.0,
                metadata={"kind": "fact"},
            ))
        for content in prefs:
            out.append(MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content=content,
                score=1.0,
                metadata={"kind": "preference"},
            ))
        return out[:limit]

    async def _recall_constraint(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        rules = await self.constraints.get_relevant(query, user_id, limit)
        return [
            MemoryHit(
                type=MemoryType.CONSTRAINT,
                content=rule,
                score=1.0,
                metadata={"priority": "high"},
            )
            for rule in rules
        ]

    # ── Fan-out (AUTO) ─────────────────────────────────────────────────

    async def _recall_auto(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        """Parallel fan-out to all reading stores, merged & sorted by score.

        ERROR is skipped (write-only in V1). Each store gets `limit` slots
        in its own search, then we keep the top `limit` across the merged
        pool. Constraints are de-prioritised slightly so semantic/episodic
        hits surface first when both score equally (constraints are
        injected separately into the system prompt).
        """
        results = await asyncio.gather(
            self._recall_episodic(query, user_id, limit),
            self._recall_semantic_user(query, user_id, limit),
            self._recall_constraint(query, user_id, limit),
            return_exceptions=True,
        )
        merged: list[MemoryHit] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("recall_auto fan-out branch failed: %s", r)
                continue
            merged.extend(r)
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:limit]


@lru_cache(maxsize=1)
def get_memory_recall_service() -> MemoryRecallService:
    return MemoryRecallService()
