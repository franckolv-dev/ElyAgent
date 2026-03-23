"""Hybrid vector + full-text memory backed by Qdrant + SQLite FTS5.

Three Qdrant collections:
- ``memories``             — summarised facts and per-fact user profile items
- ``security_constraints`` — permanent security rules learned from user refusals
- ``interactions``         — individual Q&A pairs for semantic retrieval

Every item is also indexed in the SQLite FTS5 table (see ``fts_store.py``)
for keyword / prefix matching.

Search strategy (per query)
----------------------------
1. Fetch ``limit * 4`` vector-similar candidates from Qdrant.
2. In parallel, query the FTS5 index for matching Qdrant point IDs.
3. For each candidate, compute:
       hybrid = (α × vector_score  +  β × keyword_score  +  γ × fts_boost)
                × time_decay
4. Re-rank and return the top ``limit`` results.

Decay rates (exponential e^{-λ × age_days}):
- constraints  : λ = 0.00 → permanent (security rules never expire)
- memories     : λ = 0.01 → ~69-day half-life
- interactions : λ = 0.05 → ~14-day half-life (recent exchanges preferred)

Uses fastembed (ONNX, CPU-friendly) for local embeddings — no GPU needed.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)

_COLLECTION_MEMORIES = "memories"
_COLLECTION_CONSTRAINTS = "security_constraints"
_COLLECTION_INTERACTIONS = "interactions"
_VECTOR_DIM = 384  # all-MiniLM-L6-v2 output dimension

# French + English stop-words — ignored during keyword matching
_STOP_WORDS: frozenset[str] = frozenset({
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "à", "au",
    "aux", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "me",
    "te", "se", "que", "qui", "quoi", "où", "comment", "quand", "pourquoi",
    "ce", "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa", "pas", "ne",
    "plus", "par", "sur", "sous", "dans", "avec", "pour", "sans", "est",
    "the", "a", "an", "of", "in", "is", "it", "to", "for", "on", "with",
    "are", "was", "were", "be", "been", "have", "has", "had", "do", "did",
})


class MemoryManager:
    def __init__(self) -> None:
        self._client = None
        self._encoder = None

    # ------------------------------------------------------------------ #
    # Lazy-initialised dependencies                                        #
    # ------------------------------------------------------------------ #

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=get_settings().qdrant_url)
        return self._client

    @property
    def encoder(self):
        if self._encoder is None:
            from fastembed import TextEmbedding
            self._encoder = TextEmbedding(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
        return self._encoder

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    async def init_collections(self) -> None:
        try:
            from qdrant_client.models import Distance, VectorParams
            collections_resp = await asyncio.to_thread(self.client.get_collections)
            existing = {c.name for c in collections_resp.collections}
            for name in (
                _COLLECTION_MEMORIES,
                _COLLECTION_CONSTRAINTS,
                _COLLECTION_INTERACTIONS,
            ):
                if name not in existing:
                    await asyncio.to_thread(
                        self.client.create_collection,
                        name,
                        vectors_config=VectorParams(
                            size=_VECTOR_DIM, distance=Distance.COSINE
                        ),
                    )
            logger.info("Qdrant collections ready")
        except Exception as exc:
            logger.warning("Qdrant unavailable — memory disabled: %s", exc)

    # ------------------------------------------------------------------ #
    # Scoring helpers (pure static — no I/O)                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _time_decay(created_at_ts: float | None, lambda_decay: float) -> float:
        """Exponential decay factor ∈ (0, 1].

        Returns 1.0 when lambda_decay == 0 (no decay) or when the timestamp
        is missing (backward-compatibility with items stored before this
        feature was introduced).
        """
        if created_at_ts is None or lambda_decay == 0.0:
            return 1.0
        age_days = max(0.0, (time.time() - created_at_ts) / 86400.0)
        return math.exp(-lambda_decay * age_days)

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Fraction of significant query words that appear in *text*.

        Normalised to [0, 1].  Words ≤ 2 chars and stop-words are ignored.
        Returns 0 when no significant words remain.
        """
        words = {
            w.strip(".,!?;:\"'()[]")
            for w in query.lower().split()
            if len(w.strip(".,!?;:\"'()[]")) > 2
        } - _STOP_WORDS
        if not words:
            return 0.0
        text_lower = text.lower()
        matches = sum(1 for w in words if w in text_lower)
        return matches / len(words)

    # ------------------------------------------------------------------ #
    # Low-level Qdrant helpers                                            #
    # ------------------------------------------------------------------ #

    def _embed(self, text: str) -> list[float]:
        return list(self.encoder.embed([text]))[0].tolist()

    async def _upsert(self, collection: str, vector: list[float], payload: dict) -> str:
        """Insert or update a Qdrant point (non-blocking via asyncio.to_thread).

        Automatically stamps ``created_at`` (Unix timestamp).
        Returns the generated point UUID string so callers can also index
        the item in the FTS store using the same ID.
        """
        from qdrant_client.models import PointStruct
        point_id = str(uuid.uuid4())
        stamped = {"created_at": time.time(), **payload}
        await asyncio.to_thread(
            self.client.upsert,
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=vector, payload=stamped)],
        )
        return point_id

    async def _qdrant_candidates(
        self,
        collection: str,
        vector: list[float],
        user_id: str,
        limit: int,
        score_threshold: float,
    ) -> list:
        """Async Qdrant ANN search — runs in a thread to avoid blocking the event loop."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        result = await asyncio.to_thread(
            self.client.query_points,
            collection_name=collection,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            # Fetch extra candidates so re-ranking has material to work with.
            # Relax threshold slightly to surface keyword-rich but less
            # vector-similar items before re-ranking.
            limit=limit * 4,
            score_threshold=max(0.0, score_threshold - 0.15),
            with_payload=True,
        )
        return result.points

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
        """Re-rank *candidates* using the hybrid scoring formula.

        hybrid = (α × vector_score  +  β × keyword_score  +  γ × fts_boost)
                 × time_decay
        """
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
        alpha: float = 0.65,   # weight: vector similarity
        beta: float = 0.25,    # weight: keyword overlap
        fts_boost: float = 0.10,  # additive bonus when FTS also matches
    ) -> list:
        """Full hybrid search: Qdrant ANN + FTS5 boost + temporal decay.

        Steps:
        1. Run FTS5 search (async) to collect matching Qdrant point IDs.
        2. Run Qdrant ANN (sync, fast in practice) to get vector candidates.
        3. Re-rank candidates with the hybrid formula and return top ``limit``.
        """
        from app.services.fts_store import get_fts_store

        # FTS search runs first; it's cheap and helps boost exact matches
        fts_matches = set(
            await get_fts_store().search(
                query, user_id, collection, limit=limit * 4
            )
        )

        candidates = await self._qdrant_candidates(
            collection, vector, user_id, limit, score_threshold
        )
        if not candidates:
            return []

        return self._rerank(
            candidates, query, text_fields,
            fts_matches, decay_lambda, alpha, beta, fts_boost, limit,
        )

    # ------------------------------------------------------------------ #
    # Security constraints (permanent — no decay)                         #
    # ------------------------------------------------------------------ #

    async def store_constraint(self, rule: str, user_id: str) -> None:
        try:
            point_id = await self._upsert(
                _COLLECTION_CONSTRAINTS,
                self._embed(rule),
                {"rule": rule, "user_id": user_id, "priority": "high"},
            )
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(rule, user_id, _COLLECTION_CONSTRAINTS, point_id)
        except Exception as exc:
            logger.warning("Failed to store constraint: %s", exc)

    async def get_relevant_constraints(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[str]:
        try:
            hits = await self._search_hybrid(
                _COLLECTION_CONSTRAINTS,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.4,
                text_fields=["rule"],
                decay_lambda=0.0,      # Security rules never decay
                fts_boost=0.15,        # Slightly higher boost — exact keyword matters for security
            )
            return [h.payload["rule"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch constraints: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Episodic memory (slow decay — long-lived facts)                     #
    # ------------------------------------------------------------------ #

    async def store_memory(
        self, content: str, user_id: str, conversation_id: str
    ) -> None:
        try:
            point_id = await self._upsert(
                _COLLECTION_MEMORIES,
                self._embed(content),
                {"content": content, "user_id": user_id, "conversation_id": conversation_id},
            )
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(content, user_id, _COLLECTION_MEMORIES, point_id)
        except Exception as exc:
            logger.warning("Failed to store memory: %s", exc)

    async def get_relevant_memories(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[str]:
        try:
            hits = await self._search_hybrid(
                _COLLECTION_MEMORIES,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.45,
                text_fields=["content"],
                decay_lambda=0.01,     # ~69-day half-life
            )
            return [h.payload["content"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch memories: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Interaction history (medium decay — recent exchanges preferred)     #
    # ------------------------------------------------------------------ #

    async def store_interaction(
        self,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        """Store a complete Q&A pair for future semantic retrieval."""
        try:
            content = f"Question: {user_msg}\nRéponse: {assistant_msg}"
            # Embed the user query (what we'll search by later)
            point_id = await self._upsert(
                _COLLECTION_INTERACTIONS,
                self._embed(user_msg),
                {
                    "user_message": user_msg,
                    "assistant_message": assistant_msg,
                    "content": content,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                },
            )
            # Index both sides in FTS so either can surface the interaction
            from app.services.fts_store import get_fts_store
            await get_fts_store().store(content, user_id, _COLLECTION_INTERACTIONS, point_id)
        except Exception as exc:
            logger.warning("Failed to store interaction: %s", exc)

    async def get_relevant_interactions(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[dict]:
        """Retrieve past Q&A pairs semantically similar to *query*."""
        try:
            hits = await self._search_hybrid(
                _COLLECTION_INTERACTIONS,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.5,
                text_fields=["user_message", "assistant_message"],
                decay_lambda=0.05,     # ~14-day half-life
            )
            return [h.payload for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch interactions: %s", exc)
            return []


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()
