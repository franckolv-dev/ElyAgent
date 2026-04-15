"""Unit tests for rag_detector.should_search_knowledge.

The detector is the gate in front of the agentic RAG tool.  It decides whether
a search is worth issuing based on (a) whether the user has any documents and
(b) whether the query matches either a trigger phrase or a fast similarity
probe.

Run with:  cd backend && uv run --with pytest pytest tests/test_rag_detector.py -v

Implementation note: ``should_search_knowledge`` imports
``get_rag_service`` inline via ``from app.services.rag_service import
get_rag_service``, so the patch target is the source module, not the
detector module.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.rag_detector import _TRIGGER_RE, should_search_knowledge


# ---------------------------------------------------------------------------
# Pure regex tests — no I/O
# ---------------------------------------------------------------------------

class TestTriggerKeywords:
    @pytest.mark.parametrize("query", [
        "que dit le contrat ?",
        "cherche dans mes documents",
        "d'apres le rapport, quel est le total ?",
        "résume le fichier que j'ai envoyé",
        "trouve dans mes fichiers",
        "selon le manuel utilisateur",
        "what do my documents say about X?",
        "according to the pdf I uploaded",
        "donne-moi la facture",
        "ouvre le devis",
    ])
    def test_french_and_english_triggers(self, query):
        assert _TRIGGER_RE.search(query) is not None, f"Expected trigger match in: {query}"

    @pytest.mark.parametrize("query", [
        "quel temps fait-il à Paris ?",
        "envoie un mail à Alice",
        "bonjour",
        "c'est quoi le kubernetes ?",
        "mets le minuteur à 5 minutes",
    ])
    def test_non_trigger_queries(self, query):
        assert _TRIGGER_RE.search(query) is None, f"Should not match: {query}"


# ---------------------------------------------------------------------------
# Full detector flow (async, mocked RAG backend)
# ---------------------------------------------------------------------------

def _fake_rag(has_docs: bool, top_score: float = 0.0):
    """Build a minimal RAGService double (sync client.scroll + async search)."""
    def scroll(**kwargs):
        return ([object()] if has_docs else [], None)

    async def search_knowledge(query, user_id, limit=5, score_threshold=0.4):
        if has_docs and top_score >= score_threshold:
            return [{"score": top_score, "content": "snippet"}]
        return []

    rag = type("R", (), {})()
    rag.client = type("C", (), {})()
    rag.client.scroll = scroll
    rag.search_knowledge = search_knowledge
    return rag


@pytest.mark.asyncio
async def test_short_circuit_when_no_documents():
    """No documents → no search, regardless of the query."""
    with patch(
        "app.services.rag_service.get_rag_service",
        return_value=_fake_rag(has_docs=False),
    ):
        ok, _ = await should_search_knowledge("que dit le contrat ?", "u-1")
    assert ok is False


@pytest.mark.asyncio
async def test_keyword_match_wins_without_probe():
    """A clear French trigger phrase triggers the search immediately."""
    rag = _fake_rag(has_docs=True, top_score=0.0)
    rag.search_knowledge = AsyncMock(return_value=[])  # probe would be []

    with patch("app.services.rag_service.get_rag_service", return_value=rag):
        ok, refined = await should_search_knowledge("que dit le rapport ?", "u-1")

    assert ok is True
    assert refined == "que dit le rapport ?"
    # Keyword match short-circuits before any probe call
    rag.search_knowledge.assert_not_called()


@pytest.mark.asyncio
async def test_similarity_probe_fires_when_keyword_misses():
    """No keyword match, but the probe finds a relevant chunk."""
    rag = _fake_rag(has_docs=True, top_score=0.72)

    with patch("app.services.rag_service.get_rag_service", return_value=rag):
        ok, _ = await should_search_knowledge(
            "quelle est la clause de résiliation ?", "u-1", score_threshold=0.50,
        )
    assert ok is True


@pytest.mark.asyncio
async def test_no_keyword_no_probe_means_no_search():
    """Everything negative → False."""
    rag = _fake_rag(has_docs=True, top_score=0.0)

    with patch("app.services.rag_service.get_rag_service", return_value=rag):
        ok, _ = await should_search_knowledge("bonjour, comment ca va ?", "u-1")
    assert ok is False


@pytest.mark.asyncio
async def test_safe_fallback_on_exception():
    """Any RAG error returns (False, query) instead of raising."""
    def _raise(**kwargs):
        raise RuntimeError("qdrant is on fire")

    broken = type("R", (), {})()
    broken.client = type("C", (), {})()
    broken.client.scroll = _raise
    broken.search_knowledge = AsyncMock(side_effect=RuntimeError("nope"))

    with patch("app.services.rag_service.get_rag_service", return_value=broken):
        ok, refined = await should_search_knowledge("some query", "u-1")
    assert ok is False
    assert refined == "some query"
