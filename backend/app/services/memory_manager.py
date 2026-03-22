"""Hybrid vector memory backed by Qdrant.

Three collections:
- ``memories``            — summarised facts about past conversations
- ``security_constraints``— permanent security rules learned from user refusals
- ``interactions``        — individual Q&A pairs for semantic retrieval

Search strategy (per query):
1. Fetch ``limit * 4`` vector-similar candidates from Qdrant.
2. For each candidate, compute a hybrid score:
       hybrid = (α × vector_score  +  β × keyword_score) × time_decay
3. Re-rank and return the top ``limit`` results.

Decay rates (exponential, e^{-λ × age_days}):
- constraints  : λ = 0.00  → no decay (permanent security rules)
- memories     : λ = 0.01  → ~69-day half-life (long-term facts)
- interactions : λ = 0.05  → ~14-day half-life (recent exchanges preferred)

Uses fastembed (ONNX, CPU-friendly) for local embeddings.
"""
from __future__ import annotations

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

# French + English stop-words to ignore during keyword matching
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
            self._encoder = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        return self._encoder

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    async def init_collections(self) -> None:
        try:
            from qdrant_client.models import Distance, VectorParams
            existing = {c.name for c in self.client.get_collections().collections}
            for name in (_COLLECTION_MEMORIES, _COLLECTION_CONSTRAINTS, _COLLECTION_INTERACTIONS):
                if name not in existing:
                    self.client.create_collection(
                        name,
                        vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
                    )
            logger.info("Qdrant collections ready")
        except Exception as exc:
            logger.warning("Qdrant unavailable — memory disabled: %s", exc)

    # ------------------------------------------------------------------ #
    # Scoring helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _time_decay(created_at_ts: float | None, lambda_decay: float = 0.02) -> float:
        """Exponential decay factor in [0, 1].

        Returns 1.0 for brand-new items and decreases for older ones.
        Returns 1.0 when lambda_decay == 0 (no decay) or when timestamp is missing
        (backward-compatibility with items stored before this feature).
        """
        if created_at_ts is None or lambda_decay == 0.0:
            return 1.0
        age_days = max(0.0, (time.time() - created_at_ts) / 86400.0)
        return math.exp(-lambda_decay * age_days)

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Fraction of significant query words that appear in *text*.

        Normalised to [0, 1]. Words shorter than 3 characters and stop-words
        are ignored.  Returns 0 if no significant words remain after filtering.
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
    # Low-level helpers                                                    #
    # ------------------------------------------------------------------ #

    def _embed(self, text: str) -> list[float]:
        return list(self.encoder.embed([text]))[0].tolist()

    def _upsert(self, collection: str, vector: list[float], payload: dict) -> None:
        """Insert or update a point.  Automatically stamps ``created_at``."""
        from qdrant_client.models import PointStruct
        stamped = {"created_at": time.time(), **payload}
        self.client.upsert(
            collection_name=collection,
            points=[PointStruct(id=str(uuid.uuid4()), vector=vector, payload=stamped)],
        )

    def _search_hybrid(
        self,
        collection: str,
        query: str,
        vector: list[float],
        user_id: str,
        limit: int,
        score_threshold: float,
        text_fields: list[str],
        decay_lambda: float = 0.02,
        alpha: float = 0.7,   # weight for vector similarity
        beta: float = 0.3,    # weight for keyword score
    ) -> list:
        """Fetch candidates via ANN then re-rank with keyword boost + time decay.

        Steps:
        1. Retrieve ``limit * 4`` candidates from Qdrant (lower threshold to get
           more candidates before re-ranking).
        2. Compute per-candidate hybrid score.
        3. Sort descending and return the top ``limit`` points.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # Pull extra candidates so re-ranking has material to work with
        candidates = self.client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=limit * 4,
            # Relax threshold slightly so keyword-rich but less similar items surface
            score_threshold=max(0.0, score_threshold - 0.15),
            with_payload=True,
        ).points

        if not candidates:
            return []

        scored: list[tuple[float, object]] = []
        for hit in candidates:
            # Concatenate all relevant text fields for keyword matching
            text = " ".join(str(hit.payload.get(f, "")) for f in text_fields)
            kw = self._keyword_score(query, text)
            decay = self._time_decay(hit.payload.get("created_at"), decay_lambda)
            hybrid = (alpha * hit.score + beta * kw) * decay
            scored.append((hybrid, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in scored[:limit]]

    # ------------------------------------------------------------------ #
    # Security constraints (permanent — no decay)                         #
    # ------------------------------------------------------------------ #

    async def store_constraint(self, rule: str, user_id: str) -> None:
        try:
            self._upsert(
                _COLLECTION_CONSTRAINTS,
                self._embed(rule),
                {"rule": rule, "user_id": user_id, "priority": "high"},
            )
        except Exception as exc:
            logger.warning("Failed to store constraint: %s", exc)

    async def get_relevant_constraints(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[str]:
        try:
            hits = self._search_hybrid(
                _COLLECTION_CONSTRAINTS,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.4,
                text_fields=["rule"],
                decay_lambda=0.0,   # Security rules never decay
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
            self._upsert(
                _COLLECTION_MEMORIES,
                self._embed(content),
                {"content": content, "user_id": user_id, "conversation_id": conversation_id},
            )
        except Exception as exc:
            logger.warning("Failed to store memory: %s", exc)

    async def get_relevant_memories(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[str]:
        try:
            hits = self._search_hybrid(
                _COLLECTION_MEMORIES,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.45,
                text_fields=["content"],
                decay_lambda=0.01,  # ~69-day half-life
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
        """Store a complete interaction (user query + assistant response)."""
        try:
            content = f"Question: {user_msg}\nRéponse: {assistant_msg}"
            self._upsert(
                _COLLECTION_INTERACTIONS,
                self._embed(user_msg),  # embed the query for semantic search
                {
                    "user_message": user_msg,
                    "assistant_message": assistant_msg,
                    "content": content,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                },
            )
        except Exception as exc:
            logger.warning("Failed to store interaction: %s", exc)

    async def get_relevant_interactions(
        self, query: str, user_id: str, limit: int = 3
    ) -> list[dict]:
        """Retrieve past interactions semantically similar to the current query."""
        try:
            hits = self._search_hybrid(
                _COLLECTION_INTERACTIONS,
                query,
                self._embed(query),
                user_id,
                limit,
                score_threshold=0.5,
                text_fields=["user_message", "assistant_message"],
                decay_lambda=0.05,  # ~14-day half-life
            )
            return [h.payload for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch interactions: %s", exc)
            return []


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()
