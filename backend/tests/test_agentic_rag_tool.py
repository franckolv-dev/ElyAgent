"""Unit tests for smart_knowledge_query -- the agentic RAG tool.

The tool combines the cheap gate (rag_detector) with enriched retrieval +
document-level reranking.  We patch the two async functions it depends on
so no real Qdrant instance is required.

Run with:  cd backend && uv run --with pytest pytest tests/test_agentic_rag_tool.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.agentic_rag_tool import smart_knowledge_query


# The tool is a LangChain @tool → invoke the underlying coroutine via .ainvoke
async def _invoke(query: str, user_id: str = "u-1") -> str:
    return await smart_knowledge_query.ainvoke(
        {"query": query, "user_id": user_id}
    )


@pytest.mark.asyncio
async def test_short_circuits_when_detector_says_no():
    """Detector returns False → no retrieval, clear sentinel string."""
    with patch(
        "app.agent.tools.agentic_rag_tool.should_search_knowledge",
        new=AsyncMock(return_value=(False, "anything")),
    ):
        result = await _invoke("quel temps fait-il ?")

    assert "__NO_RELEVANT_DOCS__" in result


@pytest.mark.asyncio
async def test_returns_sentinel_when_probe_positive_but_retrieval_empty():
    """Detector says True, but enriched search returns []."""
    fake_rag = type("R", (), {
        "search_knowledge": AsyncMock(return_value=[]),
    })()

    with patch(
        "app.agent.tools.agentic_rag_tool.should_search_knowledge",
        new=AsyncMock(return_value=(True, "question")),
    ), patch(
        "app.agent.tools.agentic_rag_tool.get_rag_service",
        return_value=fake_rag,
    ):
        result = await _invoke("question ambiguë")

    assert "__NO_RELEVANT_DOCS__" in result


@pytest.mark.asyncio
async def test_reranks_documents_and_formats_response():
    """Happy path: multiple chunks from the same doc get a boost; output has sources."""
    chunks = [
        {
            "source_file": "contrat.pdf", "chunk_index": 0, "total_chunks": 4,
            "content": "Clause 1: bla bla", "score": 0.80,
        },
        {
            "source_file": "contrat.pdf", "chunk_index": 2, "total_chunks": 4,
            "content": "Clause 3: bli bli", "score": 0.75,
        },
        {
            "source_file": "random.pdf", "chunk_index": 0, "total_chunks": 1,
            "content": "Quelque chose sans rapport", "score": 0.78,
        },
    ]
    fake_rag = type("R", (), {
        "search_knowledge": AsyncMock(return_value=chunks),
    })()

    with patch(
        "app.agent.tools.agentic_rag_tool.should_search_knowledge",
        new=AsyncMock(return_value=(True, "clause")),
    ), patch(
        "app.agent.tools.agentic_rag_tool.get_rag_service",
        return_value=fake_rag,
    ):
        result = await _invoke("que dit la clause 1 ?")

    # Header mentions the count
    assert "Recherche dans la base de connaissances" in result
    assert "3 retrouves" in result or "3 retrouvés" in result or "3" in result
    # Every chunk shown with source citation
    assert "contrat.pdf" in result
    assert "chunk 1/4" in result
    # Combined score appears
    assert "score combine" in result or "score combiné" in result


@pytest.mark.asyncio
async def test_top_ranked_chunk_comes_from_doc_with_most_matches():
    """Doc-level boost should reward documents with multiple matching chunks.

    Boost formula: ``combined = base + min(doc_aggregate * 0.15, 0.25)``.
    - A has one chunk at 0.70 → aggregate 0.70 → boost 0.105 → combined 0.805.
    - B has three chunks at 0.60 → aggregate 1.80 → boost capped at 0.25
      → combined 0.85 for each B chunk.
    Result: B wins despite lower raw per-chunk score.
    """
    chunks = [
        {"source_file": "A.pdf", "chunk_index": 0, "total_chunks": 1,
         "content": "A-only", "score": 0.70},
        {"source_file": "B.pdf", "chunk_index": 0, "total_chunks": 3,
         "content": "B-first", "score": 0.60},
        {"source_file": "B.pdf", "chunk_index": 1, "total_chunks": 3,
         "content": "B-second", "score": 0.60},
        {"source_file": "B.pdf", "chunk_index": 2, "total_chunks": 3,
         "content": "B-third", "score": 0.60},
    ]
    fake_rag = type("R", (), {
        "search_knowledge": AsyncMock(return_value=chunks),
    })()

    with patch(
        "app.agent.tools.agentic_rag_tool.should_search_knowledge",
        new=AsyncMock(return_value=(True, "q")),
    ), patch(
        "app.agent.tools.agentic_rag_tool.get_rag_service",
        return_value=fake_rag,
    ):
        result = await _invoke("q")

    # The first chunk displayed should come from B (doc boost wins)
    first_chunk_block = result.split("\n\n---\n\n")[0]
    assert "B.pdf" in first_chunk_block
