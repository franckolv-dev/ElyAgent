# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/knowledge_tool.py
# @brief      Knowledge base agent tools — search and list documents in the RAG pipeline
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
"""Knowledge base agent tools — search and list documents in the RAG pipeline.

These tools allow the agent to search the user's personal knowledge base
(documents ingested via the /api/knowledge/ingest endpoint) and list all
indexed documents.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.rag_service import get_rag_service


@tool
async def knowledge_search(
    query: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Recherche dans la base de connaissances personnelle de l'utilisateur.

    Utilise cet outil quand l'utilisateur pose une question sur un document
    qu'il a telecharge ou ajoute a sa base de connaissances.
    Exemples : "que dit le contrat ?", "resume le rapport", "trouve dans mes documents",
    "qu'est-ce que dit la facture ?", "cherche dans mes fichiers".

    Args:
        query: La question ou les termes de recherche
    """
    rag = get_rag_service()
    results = await rag.search_knowledge(query, user_id)

    if not results:
        return "Aucun document pertinent trouve dans ta base de connaissances."

    parts = []
    for r in results:
        source = r.get("source_file", "inconnu")
        chunk_idx = r.get("chunk_index", 0)
        total = r.get("total_chunks", 0)
        content = r.get("content", "")
        score = r.get("score", 0.0)
        parts.append(
            f"[Source: {source}, chunk {chunk_idx + 1}/{total}, pertinence: {score:.2f}]\n{content}"
        )

    return "\n\n---\n\n".join(parts)


@tool
async def knowledge_list(
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Liste tous les documents dans la base de connaissances de l'utilisateur.

    Utilise cet outil quand l'utilisateur demande la liste de ses documents indexes,
    ou veut savoir ce qui se trouve dans sa base de connaissances.
    Exemples : "quels documents j'ai ?", "liste mes fichiers indexes",
    "qu'est-ce que tu connais comme documents ?".
    """
    rag = get_rag_service()
    docs = await rag.list_documents(user_id)

    if not docs:
        return "Aucun document dans ta base de connaissances pour le moment."

    lines = []
    for d in docs:
        title = d.get("title", "Sans titre")
        source = d.get("source_file", "")
        chunks = d.get("chunk_count", 0)
        doc_id = d.get("document_id", "")
        lines.append(f"- {title} ({source}) : {chunks} chunks [ID: {doc_id[:8]}]")

    return f"{len(docs)} document(s) indexes :\n" + "\n".join(lines)
