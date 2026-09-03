# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/_infra.py
# @brief      Shared infrastructure for the typed memory stores — single
#             Qdrant client, fastembed encoder, and bounded LRU embed cache.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Lazy-initialised, process-wide singletons for the memory subpackage.

Every typed store reuses the same Qdrant connection, the same fastembed
encoder, and the same embedding cache — three benefits:

  1. ONNX model loaded once (cold start cost paid once, not per-store).
  2. Same query → same vector across stores (cache hits multiply with
     fan-out in `memory_recall(type=AUTO)`).
  3. Single Qdrant gRPC channel — fewer file descriptors.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
import time
from collections import OrderedDict
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)


class _LRUCache(OrderedDict):
    """Bounded LRU cache — evicts least-recently-used on overflow."""

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
            self.popitem(last=False)


class MemoryInfra:
    """Process-wide infra shared by every store.

    Holds the Qdrant client, the fastembed encoder, and a bounded LRU cache
    of embeddings keyed by raw text. Each store receives the same instance
    and uses `embed()` / `upsert()` / `qdrant_candidates()` on it.
    """

    def __init__(self) -> None:
        self._client = None
        self._encoder = None
        self._embed_cache: _LRUCache = _LRUCache(maxsize=2048)
        # Un verrou PAR TEXTE (audit 02/09/2026) : le verrou global unique
        # sérialisait tous les embeddings du processus, y compris cinq textes
        # différents demandés par cinq stores. Le même texte demandé cinq fois
        # reste calculé une fois ; deux textes différents avancent ensemble.
        self._embed_locks: dict[str, asyncio.Lock] = {}

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
            cache_dir = os.environ.get("FASTEMBED_CACHE_DIR", "/app/.cache/fastembed")
            os.makedirs(cache_dir, exist_ok=True)
            self._encoder = TextEmbedding(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                cache_dir=cache_dir,
            )
        return self._encoder

    async def embed(self, text: str) -> list[float]:
        """Compute embedding with LRU caching + double-checked locking.

        fastembed is CPU-bound (~50–200 ms). The same query text is embedded
        up to 5× per turn (one per store in fan-out). The lock ensures only
        one coroutine runs the model while the others wait and reuse.
        """
        if text in self._embed_cache:
            return self._embed_cache[text]
        lock = self._embed_locks.setdefault(text, asyncio.Lock())
        try:
            async with lock:
                if text in self._embed_cache:
                    return self._embed_cache[text]
                result = await asyncio.to_thread(
                    lambda: list(self.encoder.embed([text]))[0].tolist()
                )
                self._embed_cache[text] = result
        finally:
            # Le dernier sorti éteint la lumière : un verrou ne vit que le
            # temps du calcul, sinon le dict grossirait avec chaque texte vu.
            if not lock.locked():
                self._embed_locks.pop(text, None)
        return result

    async def upsert(self, collection: str, vector: list[float], payload: dict) -> str:
        """Insert/update a Qdrant point with a fresh UUID.

        Stamps `created_at` with the current Unix timestamp **only when the
        caller hasn't already set it** — preserves any ISO 8601 timestamp
        a caller (e.g. `SemanticUserStore.store`) chose to put in the payload.
        """
        from qdrant_client.models import PointStruct
        point_id = str(uuid.uuid4())
        stamped = dict(payload)
        stamped.setdefault("created_at", time.time())
        await asyncio.to_thread(
            self.client.upsert,
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=vector, payload=stamped)],
        )
        return point_id

    async def qdrant_candidates(
        self,
        collection: str,
        vector: list[float],
        user_id: str,
        limit: int,
        score_threshold: float,
    ) -> list:
        """Async Qdrant ANN search — user-scoped, runs in a thread.

        Refuses empty user_id (would cross-tenant leak). Anonymous flows
        must pass an explicit sentinel like `"__anon__"`.
        """
        if not user_id:
            logger.warning(
                "Qdrant candidates query refused: empty user_id on collection=%s "
                "(would have leaked across tenants — returning [])", collection
            )
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        result = await asyncio.to_thread(
            self.client.query_points,
            collection_name=collection,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=limit * 4,
            score_threshold=max(0.0, score_threshold - 0.15),
            with_payload=True,
        )
        return result.points


    # ── Surface d'inspection (page « Mes mémoires », §2.5.6) ────────────
    # La recherche par pertinence ne suffit pas à auditer : pour savoir ce
    # qu'Ely retient, il faut pouvoir TOUT parcourir, sans requête. D'où ces
    # deux primitives, qui n'existent que pour l'inspection humaine.

    async def scroll_entries(
        self,
        collection: str,
        user_id: str,
        limit: int,
        offset: str | None = None,
    ) -> tuple[list, str | None]:
        """Parcours paginé des points d'un utilisateur — (points, offset suivant).

        Refuse un ``user_id`` vide, comme `qdrant_candidates` : ici la fuite
        serait pire, il n'y a pas de requête pour restreindre le résultat.

        ⚠️ Le curseur transite en **chaîne**. Ça tient parce que tous les points
        de ce dépôt sont créés avec un UUID en chaîne (`upsert` fait
        `str(uuid.uuid4())`, `store_preference` réutilise `str(existing.id)`) et
        que Qdrant réaccepte un UUID textuel. Sur une collection à identifiants
        ENTIERS, `str(42)` repartirait en `"42"` et le parcours boucherait à la
        première page — il faudrait alors typer le curseur.

        Laisse remonter ses erreurs : c'est l'appelant (`inspection.list_entries`)
        qui décide de dégrader en page vide.
        """
        if not user_id:
            logger.warning(
                "Scroll refused: empty user_id on collection=%s "
                "(would have listed every tenant — returning [])", collection
            )
            return [], None
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        points, next_offset = await asyncio.to_thread(
            self.client.scroll,
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        return points, (str(next_offset) if next_offset is not None else None)

    async def delete_point(
        self, collection: str, point_id: str, user_id: str
    ) -> bool:
        """Supprimer UN point, à condition qu'il appartienne à *user_id*.

        Le filtre porte sur l'identifiant ET le propriétaire dans la MÊME
        requête. Relire le point puis le supprimer laisserait une fenêtre
        entre les deux, et surtout ferait reposer la garde sur du code
        appelant — ici Qdrant ne peut pas supprimer le point d'un tiers, même
        si l'appelant se trompe.

        Rend `True` si un point a bien été retiré — le routeur en fait un 404,
        pour ne pas confirmer l'existence d'un identifiant qui n'est pas à
        l'appelant.
        """
        if not user_id or not point_id:
            return False
        from qdrant_client.models import (
            FieldCondition, Filter, FilterSelector, HasIdCondition, MatchValue,
        )
        selector = FilterSelector(
            filter=Filter(
                must=[
                    HasIdCondition(has_id=[point_id]),
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                ]
            )
        )
        # `count` AVANT le delete : l'opération Qdrant ne dit pas combien de
        # points elle a touchés, et « supprimé » vs « inexistant » est
        # exactement la distinction que le routeur doit rendre.
        before = await asyncio.to_thread(
            self.client.count,
            collection_name=collection,
            count_filter=selector.filter,
            exact=True,
        )
        if before.count == 0:
            return False
        await asyncio.to_thread(
            self.client.delete,
            collection_name=collection,
            points_selector=selector,
        )
        return True


@lru_cache(maxsize=1)
def get_memory_infra() -> MemoryInfra:
    return MemoryInfra()
