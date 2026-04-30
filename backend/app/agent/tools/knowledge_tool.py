# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/knowledge_tool.py
# @brief      Knowledge base agent tools — search and list documents in the RAG pipeline
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
    """Search in the user's personal knowledge base.

    Use this tool when the user asks a question about a document they have
    uploaded or added to their knowledge base.
    Examples: "what does the contract say?", "summarize the report", "find in
    my documents", "what does the invoice say?", "search in my files".

    Args:
        query: The question or search terms.
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
    """List all documents in the user's personal knowledge base.

    Use this tool when the user asks for the list of their indexed documents,
    or wants to know what is stored in their knowledge base.
    Examples: "what documents do I have?", "list my indexed files",
    "what documents do you know about?".
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
