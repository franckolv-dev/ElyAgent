# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/agentic_rag_tool.py
# @brief      Agentic RAG tool — smart knowledge base querying with auto-detection
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
"""Agentic RAG tool — smart knowledge base querying with auto-detection.

Unlike ``knowledge_search`` which is a direct lookup the agent calls on
demand, ``smart_knowledge_query`` performs a two-stage lookup:

1. **Detect**  — Use ``rag_detector.should_search_knowledge()`` to decide
   whether a search is actually worthwhile (keyword probe + similarity probe).
   If the user has no documents or the query is irrelevant, return early with
   a clear signal that the tool was a no-op.
2. **Retrieve + rerank**  — Issue a slightly broader search (limit=8),
   deduplicate by document, and return the top-N chunks ranked by a weighted
   score combining Qdrant similarity with a document-level aggregate boost.

This encourages the LLM to always *try* the knowledge base without drowning
its context when nothing relevant exists.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.rag_detector import should_search_knowledge
from app.services.rag_service import get_rag_service


@tool
async def smart_knowledge_query(
    query: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Recherche intelligente dans la base de connaissances personnelle.

    Outil "agentique" qui verifie d'abord si la requete est pertinente pour
    la base documentaire (via detection par mots-cles + probe de similarite),
    puis effectue une recherche enrichie avec reranking document-level.

    A UTILISER EN PRIORITE avant de repondre a toute question factuelle
    susceptible de concerner un document personnel. Si aucun document n'est
    pertinent, l'outil retourne un signal explicite et tu peux repondre
    normalement sans le mentionner a l'utilisateur.

    Args:
        query: La question ou les termes a rechercher.
    """
    # Stage 1 — cheap relevance gate
    should_search, refined_query = await should_search_knowledge(query, user_id)
    if not should_search:
        return "__NO_RELEVANT_DOCS__ (aucun document indexe correspondant — repondre sans citer la base)"

    # Stage 2 — enriched retrieval
    rag = get_rag_service()
    results = await rag.search_knowledge(
        refined_query, user_id, limit=8, score_threshold=0.35,
    )

    if not results:
        return "__NO_RELEVANT_DOCS__ (probe positif mais aucun chunk au-dessus du seuil)"

    # Document-level rerank: boost documents with multiple matching chunks,
    # then take the top 5 chunks by combined score.
    doc_scores: dict[str, float] = {}
    for r in results:
        doc = r.get("source_file", "")
        doc_scores[doc] = doc_scores.get(doc, 0.0) + r.get("score", 0.0)

    def _combined_score(r: dict) -> float:
        base = r.get("score", 0.0)
        doc_boost = min(doc_scores.get(r.get("source_file", ""), 0.0) * 0.15, 0.25)
        return base + doc_boost

    ranked = sorted(results, key=_combined_score, reverse=True)[:5]

    parts = []
    for r in ranked:
        source = r.get("source_file", "inconnu")
        chunk_idx = r.get("chunk_index", 0)
        total = r.get("total_chunks", 0)
        content = r.get("content", "")
        score = r.get("score", 0.0)
        combined = _combined_score(r)
        parts.append(
            f"[Source: {source}, chunk {chunk_idx + 1}/{total}, "
            f"pertinence: {score:.2f}, score combine: {combined:.2f}]\n{content}"
        )

    header = (
        f"Recherche dans la base de connaissances ({len(ranked)} extraits pertinents"
        f" sur {len(results)} retrouves) :\n\n"
    )
    return header + "\n\n---\n\n".join(parts)
