# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory_manager.py
# @brief      Hybrid vector + full-text memory backed by Qdrant + SQLite FTS5
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
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
from collections import OrderedDict
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)

_COLLECTION_MEMORIES = "memories"
_COLLECTION_CONSTRAINTS = "security_constraints"
_COLLECTION_INTERACTIONS = "interactions"
_COLLECTION_PREFERENCES = "user_profile"   # communication style, tone, habits (permanent)
_VECTOR_DIM = 384  # all-MiniLM-L6-v2 output dimension


class _LRUCache(OrderedDict):
    """MED-8: Bounded LRU cache for embeddings (evicts least-recently-used on overflow)."""

    def __init__(self, maxsize: int = 2048):
        super().__init__()
        self._maxsize = maxsize

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        if len(self) > self._maxsize:
            self.popitem(last=False)  # evict least-recently-used

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
        # Embedding cache: avoids recomputing the same vector 3× per query.
        # MED-8: bounded LRU cache (2048 entries) prevents unbounded memory growth.
        # LOW-3: double-checked locking ensures correctness under asyncio.gather.
        self._embed_cache: _LRUCache = _LRUCache(maxsize=2048)
        self._embed_lock = asyncio.Lock()

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
                _COLLECTION_PREFERENCES,
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

    async def _embed(self, text: str) -> list[float]:
        """Compute embedding with LRU caching to avoid redundant ONNX inference.

        fastembed uses ONNX (CPU-bound, ~50-200 ms).  The same query text is
        typically embedded 3× per turn (constraints, memories, interactions).
        Double-checked locking ensures only one coroutine runs the model while
        the others wait and then reuse the cached result.

        Cache is bounded to 64 entries (insertion-order eviction) to cap memory.
        """
        if text in self._embed_cache:
            return self._embed_cache[text]
        async with self._embed_lock:
            # LOW-3: Re-check after acquiring the lock — a concurrent coroutine may have
            # already computed and cached the result while we were waiting.
            if text in self._embed_cache:
                return self._embed_cache[text]
            result = await asyncio.to_thread(
                lambda: list(self.encoder.embed([text]))[0].tolist()
            )
            # MED-8: _LRUCache handles bounded eviction automatically on assignment
            self._embed_cache[text] = result
        return result

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
                await self._embed(rule),
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
                await self._embed(query),
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
                await self._embed(content),
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
                await self._embed(query),
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
                await self._embed(user_msg),
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
                await self._embed(query),
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

    # ------------------------------------------------------------------ #
    # User preferences (permanent — communication style, tone, habits)   #
    # ------------------------------------------------------------------ #

    async def store_preference(self, preference: str, user_id: str) -> None:
        """Store a user preference or communication habit (permanent, no decay).

        Unlike episodic memories (facts about the user's life), preferences
        capture *how* the user likes to interact: preferred tone, level of detail,
        response format, recurring patterns, etc.  They are stored permanently
        and always injected into the system prompt at the start of each session.

        Deduplication: if a semantically very similar preference already exists
        (cosine similarity ≥ 0.88), the new text replaces it in-place instead
        of creating a duplicate entry.  This prevents accumulation of near-identical
        preferences across sessions (e.g. "be concise" stored 5 times).
        """
        try:
            vector = await self._embed(preference)

            # ── Deduplication: look for a near-identical existing preference ─
            from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
            candidates = await asyncio.to_thread(
                self.client.query_points,
                collection_name=_COLLECTION_PREFERENCES,
                query=vector,
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=3,
                score_threshold=0.88,   # very high → only near-identical preferences
                with_payload=True,
            )

            if candidates.points:
                # Reuse the existing point ID → update in-place
                existing = candidates.points[0]
                point_id = str(existing.id)
                await asyncio.to_thread(
                    self.client.upsert,
                    collection_name=_COLLECTION_PREFERENCES,
                    points=[PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={"content": preference, "user_id": user_id,
                                 "created_at": existing.payload.get("created_at", time.time()),
                                 "updated_at": time.time()},
                    )],
                )
                logger.debug("Updated existing preference (dedup): %s", preference[:60])
            else:
                # New preference → insert
                point_id = await self._upsert(
                    _COLLECTION_PREFERENCES,
                    vector,
                    {"content": preference, "user_id": user_id},
                )
                logger.debug("Stored new preference: %s", preference[:60])

            from app.services.fts_store import get_fts_store
            await get_fts_store().store(
                preference, user_id, _COLLECTION_PREFERENCES, point_id
            )
        except Exception as exc:
            logger.warning("Failed to store preference: %s", exc)

    async def get_user_preferences(self, user_id: str, limit: int = 10) -> list[str]:
        """Retrieve all stored user preferences (scroll, no decay filter).

        Preferences are always relevant regardless of the current query, so we
        use Qdrant ``scroll`` to fetch them all (capped at *limit*) rather than
        doing a semantic search.
        """
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            result = await asyncio.to_thread(
                self.client.scroll,
                collection_name=_COLLECTION_PREFERENCES,
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


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()
