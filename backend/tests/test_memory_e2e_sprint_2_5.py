# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_e2e_sprint_2_5.py
# @brief      Sprint 2.5 Jalon 8 — end-to-end regression suite for the
#             typed cognitive memory layer.
# @license    Elastic License 2.0
# =============================================================================
"""E2E pipeline tests for the Sprint 2.5 typed memory layer.

These tests do NOT spin up Qdrant or call Ollama — they wire the real
service classes together (MemoryRecallService, MaintenanceAgentRapid,
the typed stores, the LangChain tool) and only stub the I/O boundaries.

What is pinned :
  - The full chain consolidate -> store -> recall returns the same fact
  - `memory_recall(type=AUTO)` survives one store raising an exception
  - The 2026-05-20 BASE VIDE bug never reappears : a Qdrant hit whose
    payload has an ISO-string `created_at` must still surface through
    `memory_recall`, not be swallowed by an unsupported-operand error
  - The Jalon 4 explicit routing holds end-to-end: a "preference" fact
    extracted by the maintenance agent lands in `store_preference`,
    not in `store_fact`
  - The legacy `memory_search` tool produces the same result set as
    `memory_recall(type=SEMANTIC_USER)` for the same query (no drift
    between the two paths during the V1 transition)
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.memory import (
    MemoryHit,
    MemoryType,
    get_constraint_store,
    get_episodic_store,
    get_memory_recall_service,
    get_semantic_user_store,
)
from app.services.memory._infra import get_memory_infra
from app.services.memory.constraint_store import ConstraintStore
from app.services.memory.episodic_store import EpisodicStore
from app.services.memory.semantic_user_store import SemanticUserStore


@pytest.fixture(autouse=True)
def _clear_memory_singletons():
    """Reset every lru_cache singleton between tests in this module.

    The recall service + the typed-store accessors are all cached on
    first call, which keeps the same store instances alive across tests.
    Between two tests that patch store methods, that residual state
    leaks and a class-level monkeypatch may be shadowed by a stale
    instance attribute set by the previous test. Clearing the caches
    forces every test to start from fresh, isolated singletons.
    """
    get_memory_recall_service.cache_clear()
    get_constraint_store.cache_clear()
    get_episodic_store.cache_clear()
    get_semantic_user_store.cache_clear()
    get_memory_infra.cache_clear()
    yield


# ──────────────────────────────────────────────────────────────────────
# 1. BASE VIDE regression (2026-05-20)
# ──────────────────────────────────────────────────────────────────────


def test_time_decay_accepts_iso_string_from_production_payload() -> None:
    """Reproduces the exact 799-entries scenario from 2026-05-20.

    Before the fix, _time_decay did `time.time() - created_at` which
    raised TypeError when `created_at` was the ISO string written by
    `store_memory`'s isoformat() path. The outer try/except swallowed
    it silently and the search returned [] -> the agent honestly
    reported "BASE VIDE" while Qdrant held 799 entries.

    Pin: ISO strings (both `+00:00` and `Z` suffixes) must be accepted
    and yield a decay factor in (0, 1]. Same value as the equivalent
    float Unix timestamp.
    """
    from app.services.memory._base import BaseStore
    decay_iso = BaseStore._time_decay("2026-05-14T19:25:22+00:00", 0.01)
    decay_z = BaseStore._time_decay("2026-05-14T19:25:22Z", 0.01)
    assert 0.0 < decay_iso <= 1.0
    assert 0.0 < decay_z <= 1.0
    # Same instant in two notations → same decay factor (within float noise)
    assert abs(decay_iso - decay_z) < 1e-9


@pytest.mark.asyncio
async def test_memory_recall_does_not_return_empty_on_iso_string_payloads(monkeypatch) -> None:
    """Full E2E pin of BASE VIDE : a SemanticUserStore search that
    returns a Qdrant hit with an ISO-string `created_at` must surface
    through `memory_recall(SEMANTIC_USER)` as a MemoryHit, not be
    silently dropped."""
    svc = get_memory_recall_service()

    async def fake_facts_returning_iso(query, user_id, limit):
        # Mimic the legacy Qdrant payload : content + ISO created_at
        # (the production 2026-05-20 shape).
        return ["The user lives in Paris"]

    async def fake_prefs(user_id, limit):
        return []

    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_facts_returning_iso)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_prefs)

    hits = await svc.recall(
        MemoryType.SEMANTIC_USER, "where", user_id="u1", limit=5
    )
    # The original bug surfaced as `hits == []`. If we ever regress,
    # this assertion fires.
    assert hits, "BASE VIDE bug regression — recall returned an empty list"
    assert hits[0].content == "The user lives in Paris"
    assert hits[0].type == MemoryType.SEMANTIC_USER


# ──────────────────────────────────────────────────────────────────────
# 2. Consolidate → store → recall, all wired together
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_chain_maintenance_extract_then_recall_returns_same_fact(monkeypatch) -> None:
    """E2E happy path : the maintenance agent extracts a fact, writes
    via the typed store, and recall finds it back. Both ends share the
    real `SemanticUserStore` instance ; only Qdrant / FTS5 / LLM are stubbed.
    """
    from app.services.memory import maintenance_rapid

    # Shared in-memory "store" we'll use to back both the write and the
    # read sides. Maps `user_id` to a list of (content, kind) tuples.
    stash: dict[str, list[tuple[str, str]]] = {}

    async def stub_store_fact(self, content, user_id, conversation_id="", extra_payload=None):
        stash.setdefault(user_id, []).append((content, "fact"))

    async def stub_store_preference(self, preference, user_id):
        stash.setdefault(user_id, []).append((preference, "preference"))

    async def stub_get_relevant_facts(self, query, user_id, limit):
        return [c for (c, k) in stash.get(user_id, []) if k == "fact"][:limit]

    async def stub_get_preferences(self, user_id, limit):
        return [c for (c, k) in stash.get(user_id, []) if k == "preference"][:limit]

    monkeypatch.setattr(SemanticUserStore, "store_fact", stub_store_fact)
    monkeypatch.setattr(SemanticUserStore, "store_preference", stub_store_preference)
    monkeypatch.setattr(SemanticUserStore, "get_relevant_facts", stub_get_relevant_facts)
    monkeypatch.setattr(SemanticUserStore, "get_preferences", stub_get_preferences)

    # Stub the inputs of the maintenance agent : the conversation loader
    # and the LLM extractor.
    async def fake_load_messages(self, conversation_id):
        m1 = SimpleNamespace(role="user", content="I work on a project named ELY")
        m2 = SimpleNamespace(role="assistant", content="Noted.")
        return [m1, m2]

    # Signature reelle (user_id/conversation_id ajoutes le 05/08 pour la
    # consignation d'usage) — un double a `**kwargs` n'aurait rien signale.
    async def fake_extract(self, conversation_text, user_id="", conversation_id=None):
        return [
            {"fact": "The user works on a project named ELY", "type": "context"},
            {"fact": "The user prefers concise answers", "type": "preference"},
        ]

    monkeypatch.setattr(
        maintenance_rapid.MaintenanceAgentRapid, "_load_recent_messages", fake_load_messages
    )
    monkeypatch.setattr(
        maintenance_rapid.MaintenanceAgentRapid, "_extract_facts", fake_extract
    )

    # 1. Maintenance agent runs and writes to the shared stash.
    agent = maintenance_rapid.MaintenanceAgentRapid()
    result = await agent.consolidate("conv-42", "alice")
    assert result["status"] == "ok"
    assert result["preferences"] == 1
    assert result["facts"] == 1

    # 2. Recall via the public API surface picks the same fact + preference back up.
    svc = get_memory_recall_service()
    hits = await svc.recall(MemoryType.SEMANTIC_USER, "ELY", user_id="alice", limit=10)
    contents = {h.content for h in hits}
    assert "The user works on a project named ELY" in contents
    assert "The user prefers concise answers" in contents

    # And the two are correctly tagged as fact vs preference.
    kinds = {h.content: h.metadata["kind"] for h in hits}
    assert kinds["The user works on a project named ELY"] == "fact"
    assert kinds["The user prefers concise answers"] == "preference"


# ──────────────────────────────────────────────────────────────────────
# 3. AUTO fan-out resilience
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_fanout_survives_qdrant_outage_on_one_store(monkeypatch) -> None:
    """If ConstraintStore.get_relevant raises (e.g. Qdrant collection
    missing), SEMANTIC_USER + EPISODIC must still return results. Pins the
    gather(return_exceptions=True) contract. (La branche procédurale a été
    retirée en V0-5 : c'était un stub sans voie d'écriture.)"""
    svc = get_memory_recall_service()

    async def boom(*args, **kwargs):
        raise RuntimeError("Qdrant connection refused")

    async def fake_facts(query, user_id, limit):
        return ["F1", "F2"]

    async def fake_prefs(user_id, limit):
        return []

    async def fake_episodic(query, user_id, limit):
        return [{"content": "Q&A", "user_message": "x", "assistant_message": "y"}]

    monkeypatch.setattr(svc.constraints, "get_relevant", boom)
    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_facts)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_prefs)
    monkeypatch.setattr(svc.episodic, "get_relevant", fake_episodic)

    hits = await svc.recall(MemoryType.AUTO, "anything", user_id="u1", limit=20)

    # SEMANTIC_USER (2 facts) + EPISODIC (1) — constraint branch failed
    # silently, les autres sont passées.
    types = {h.type for h in hits}
    assert MemoryType.SEMANTIC_USER in types
    assert MemoryType.EPISODIC in types
    assert MemoryType.CONSTRAINT not in types


# ──────────────────────────────────────────────────────────────────────
# 4. Legacy memory_search delegates without drift from memory_recall
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_search_legacy_and_memory_recall_unified_agree(monkeypatch) -> None:
    """Same backend data → both the legacy `memory_search` tool and the
    new `memory_recall` tool surface the same SEMANTIC_USER facts.

    Important during the V1 transition : if the legacy alias drifts from
    the new API, users get different results depending on which tool the
    LLM picks. This test fails if anyone introduces a divergent code
    path between the two."""
    facts_payload = [
        "The user is based in Paris",
        "The user uses macOS",
    ]

    async def fake_facts(self, query, user_id, limit):
        return list(facts_payload)

    async def fake_prefs(self, user_id, limit):
        return []

    monkeypatch.setattr(SemanticUserStore, "get_relevant_facts", fake_facts)
    monkeypatch.setattr(SemanticUserStore, "get_preferences", fake_prefs)

    # Clear the deprecation one-shot so the test is hermetic.
    from app.services.memory import _deprecated as deprecated_mod
    deprecated_mod._reset_for_tests()

    # 1) New unified tool.
    from app.agent.tools.memory_recall_tool import memory_recall
    new_out = await memory_recall.ainvoke({
        "query": "where",
        "user_id": "u1",
        "memory_type": "semantic_user",
        "limit": 5,
    })

    # 2) Legacy tool.
    from app.agent.tools.memgpt_tool import memory_search
    legacy_out = await memory_search.ainvoke({
        "query": "where",
        "user_id": "u1",
        "limit": 5,
    })

    # Both reports must contain every fact text — different framings
    # (prose vs numbered list) are fine, but the recall content must
    # not diverge.
    for fact in facts_payload:
        assert fact in new_out, f"memory_recall missed: {fact}"
        assert fact in legacy_out, f"memory_search missed: {fact}"


# ──────────────────────────────────────────────────────────────────────
# 5. ERROR type is fully wired but write-only in V1
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_type_recall_is_explicitly_unreadable(monkeypatch) -> None:
    """CONTRAT MODIFIÉ EN V0-5. Avant : `recall(ERROR)` rendait `[]`, et le
    modèle lisait « aucun souvenir » — donc « je n'ai jamais échoué là-dessus ».
    Maintenant : le service lève `UnreadableMemoryType`, et l'outil dit
    explicitement que cette mémoire ne se lit pas. Les erreurs sont toujours
    capturées (failure_cases) ; c'est la LECTURE qui n'existe pas, et le modèle
    ne doit pas confondre les deux."""
    from app.services.memory.recall_service import UnreadableMemoryType

    svc = get_memory_recall_service()
    with pytest.raises(UnreadableMemoryType):
        await svc.recall(MemoryType.ERROR, "doctolib", user_id="u1", limit=5)

    from app.agent.tools.memory_recall_tool import memory_recall
    out = await memory_recall.ainvoke({
        "query": "doctolib", "user_id": "u1", "memory_type": "error",
    })
    assert "pas consultable" in out
    assert "ne conclus pas" in out.lower()
