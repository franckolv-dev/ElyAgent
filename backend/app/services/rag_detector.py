# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/rag_detector.py
# @brief      RAG trigger detection -- determines if a query should search the knowledge base
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
"""RAG trigger detection -- determines if a query should search the knowledge base.

Lightweight service used by the agentic RAG tool to decide whether a user
query is likely to be answerable from the user's personal documents.

Two strategies are combined:
1. **Keyword detection** -- a set of French/English trigger phrases that
   strongly suggest the user is referring to their own documents.
2. **Fast similarity probe** -- a single-result Qdrant search against the
   ``knowledge`` collection.  If the top score exceeds the threshold the
   query is considered relevant even without explicit keywords.
"""
from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigger keywords / phrases (case-insensitive)
# ---------------------------------------------------------------------------

_TRIGGER_PHRASES: list[str] = [
    # French -- explicit document references
    r"\bdocument\b",
    r"\bfichier\b",
    r"\brapport\b",
    r"\bcontrat\b",
    r"\bfacture\b",
    r"\bpdf\b",
    r"\bnote[s]?\b",
    r"\bmemo\b",
    r"\bmanuel\b",
    r"\bguide\b",
    r"\bcahier des charges\b",
    r"\bdevis\b",
    # French -- contextual references to user's knowledge
    r"dans mes\b",
    r"selon le\b",
    r"d'apres le\b",
    r"d'apr[eè]s le\b",
    r"qu'est-ce que dit\b",
    r"que dit le\b",
    r"que dit la\b",
    r"dans le document\b",
    r"dans la base\b",
    r"dans mes fichiers\b",
    r"dans mes documents\b",
    r"cherche dans\b",
    r"trouve dans\b",
    # English equivalents
    r"\bmy documents?\b",
    r"\bmy files?\b",
    r"\bmy knowledge\b",
    r"in my\b.*\b(docs?|files?|knowledge)\b",
    r"according to\b",
    r"based on the\b",
]

_TRIGGER_RE = re.compile("|".join(_TRIGGER_PHRASES), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def should_search_knowledge(
    query: str,
    user_id: str,
    score_threshold: float = 0.50,
) -> tuple[bool, str]:
    """Determine if *query* should trigger a knowledge base search.

    Returns ``(should_search, refined_query)`` where *refined_query* is the
    original query (unchanged) -- kept for future query-rewriting extensions.

    Strategy:
    1. Check if the user has **any** documents in the knowledge collection
       (quick Qdrant point count).  If zero, return ``(False, query)``
       immediately -- no point searching an empty collection.
    2. Look for explicit trigger keywords / phrases in the query.
    3. If no keyword match, perform a fast single-result Qdrant similarity
       search.  If the top score >= *score_threshold*, return True.

    The function is intentionally **cheap**: one count RPC + at most one
    single-vector search.  It adds < 50 ms to a typical turn.
    """
    try:
        from app.services.rag_service import get_rag_service

        rag = get_rag_service()

        # Step 1 -- does the user even have documents?
        has_docs = await _user_has_documents(rag, user_id)
        if not has_docs:
            return (False, query)

        # Step 2 -- keyword / phrase detection
        if _TRIGGER_RE.search(query):
            logger.debug("RAG trigger: keyword match for '%s'", query[:80])
            return (True, query)

        # Step 3 -- fast similarity probe (limit=1)
        results = await rag.search_knowledge(
            query, user_id, limit=1, score_threshold=score_threshold,
        )
        if results:
            top_score = results[0].get("score", 0.0)
            logger.debug(
                "RAG trigger: similarity probe score=%.3f (threshold=%.2f)",
                top_score, score_threshold,
            )
            return (True, query)

        return (False, query)

    except Exception as exc:
        logger.warning("RAG detector failed (safe fallback=False): %s", exc)
        return (False, query)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _user_has_documents(rag, user_id: str) -> bool:
    """Return True if the user has at least one chunk in the knowledge collection."""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        result = await asyncio.to_thread(
            rag.client.scroll,
            collection_name="knowledge",
            scroll_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=1,
            with_payload=False,
        )
        points, _ = result
        return len(points) > 0
    except Exception:
        return False
