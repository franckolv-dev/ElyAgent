"""Vector memory backed by Qdrant.

Two collections:
- ``memories``    — summarised facts about past conversations
- ``constraints`` — permanent security rules learned from user refusals

Uses fastembed (ONNX, CPU-friendly) for local embeddings so no GPU or
heavy PyTorch installation is required.
"""
from __future__ import annotations

import logging
import uuid
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)

_COLLECTION_MEMORIES = "memories"
_COLLECTION_CONSTRAINTS = "security_constraints"
_COLLECTION_INTERACTIONS = "interactions"
_VECTOR_DIM = 384  # all-MiniLM-L6-v2 output dimension


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
    # Low-level helpers                                                    #
    # ------------------------------------------------------------------ #

    def _embed(self, text: str) -> list[float]:
        return list(self.encoder.embed([text]))[0].tolist()

    def _upsert(self, collection: str, vector: list[float], payload: dict) -> None:
        from qdrant_client.models import PointStruct
        self.client.upsert(
            collection_name=collection,
            points=[PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)],
        )

    def _search(
        self,
        collection: str,
        vector: list[float],
        user_id: str,
        limit: int,
        score_threshold: float,
    ) -> list[dict]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        return self.client.search(
            collection_name=collection,
            query_vector=vector,
            query_filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]),
            limit=limit,
            score_threshold=score_threshold,
        )

    # ------------------------------------------------------------------ #
    # Security constraints                                                 #
    # ------------------------------------------------------------------ #

    async def store_constraint(self, rule: str, user_id: str) -> None:
        try:
            self._upsert(_COLLECTION_CONSTRAINTS, self._embed(rule),
                         {"rule": rule, "user_id": user_id, "priority": "high"})
        except Exception as exc:
            logger.warning("Failed to store constraint: %s", exc)

    async def get_relevant_constraints(self, query: str, user_id: str, limit: int = 5) -> list[str]:
        try:
            hits = self._search(_COLLECTION_CONSTRAINTS, self._embed(query), user_id, limit, 0.4)
            return [h.payload["rule"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch constraints: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Episodic memory                                                      #
    # ------------------------------------------------------------------ #

    async def store_memory(self, content: str, user_id: str, conversation_id: str) -> None:
        try:
            self._upsert(_COLLECTION_MEMORIES, self._embed(content),
                         {"content": content, "user_id": user_id, "conversation_id": conversation_id})
        except Exception as exc:
            logger.warning("Failed to store memory: %s", exc)

    async def get_relevant_memories(self, query: str, user_id: str, limit: int = 3) -> list[str]:
        try:
            hits = self._search(_COLLECTION_MEMORIES, self._embed(query), user_id, limit, 0.5)
            return [h.payload["content"] for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch memories: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Interaction history                                                  #
    # ------------------------------------------------------------------ #

    async def store_interaction(self, user_msg: str, assistant_msg: str, user_id: str, conversation_id: str) -> None:
        """Store a complete interaction (user query + assistant response) for future semantic retrieval."""
        try:
            content = f"Question: {user_msg}\nRéponse: {assistant_msg}"
            self._upsert(
                _COLLECTION_INTERACTIONS,
                self._embed(user_msg),  # embed the user query for semantic search
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

    async def get_relevant_interactions(self, query: str, user_id: str, limit: int = 3) -> list[dict]:
        """Retrieve past interactions semantically similar to the current query."""
        try:
            hits = self._search(_COLLECTION_INTERACTIONS, self._embed(query), user_id, limit, 0.55)
            return [h.payload for h in hits]
        except Exception as exc:
            logger.warning("Failed to fetch interactions: %s", exc)
            return []


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()
