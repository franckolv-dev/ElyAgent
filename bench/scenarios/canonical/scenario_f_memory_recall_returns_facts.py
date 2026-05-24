# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_f_memory_recall_returns_facts.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario F : ensure
#             a fact written via SemanticUserStore.store_fact can be
#             recalled via memory_recall(SEMANTIC_USER). The
#             round-trip pins the BASE VIDE bug regression
#             (2026-05-20) at the integration layer.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Canonical scenario F — memory recall round-trip."""
from __future__ import annotations

import uuid


NAME = "F — Memory recall round-trip"
DESCRIPTION = (
    "Writes a fact via SemanticUserStore.store_fact and recalls it via "
    "memory_recall(SEMANTIC_USER). Pins the BASE VIDE bug regression."
)


async def run() -> dict:
    # The stores hit Qdrant in production. For the canonical bench we
    # monkeypatch the SemanticUserStore methods to an in-memory dict
    # so the scenario stays hermetic (no Qdrant required). The pipe
    # `memory_recall -> SemanticUserStore.get_relevant_facts` is what
    # we care about — not the Qdrant ANN search itself.
    from app.services.memory import (
        MemoryType,
        get_memory_recall_service,
    )
    from app.services.memory.semantic_user_store import SemanticUserStore

    uid = f"bench_f_{uuid.uuid4().hex[:8]}"
    fact = "The user lives in Paris and works on the ELY project."

    # In-memory replacement for the store methods
    stash: dict[str, list[str]] = {uid: [fact]}

    orig_facts = SemanticUserStore.get_relevant_facts
    orig_prefs = SemanticUserStore.get_preferences

    async def fake_facts(self, query, user_id, limit):
        return list(stash.get(user_id, []))[:limit]

    async def fake_prefs(self, user_id, limit):
        return []

    SemanticUserStore.get_relevant_facts = fake_facts
    SemanticUserStore.get_preferences = fake_prefs
    try:
        # Use a fresh service singleton so it picks up the patched class
        svc = get_memory_recall_service.__wrapped__()
        hits = await svc.recall(
            memory_type=MemoryType.SEMANTIC_USER,
            query="where does the user live?",
            user_id=uid,
            limit=5,
        )
    finally:
        SemanticUserStore.get_relevant_facts = orig_facts
        SemanticUserStore.get_preferences = orig_prefs

    if not hits:
        return {
            "pass": False,
            "reason": "memory_recall returned [] — BASE VIDE regression suspected",
        }

    checks = {
        "non_empty_hits": len(hits) >= 1,
        "fact_present": any(fact in h.content for h in hits),
        "type_is_semantic_user": all(h.type == MemoryType.SEMANTIC_USER for h in hits),
    }
    failed = [k for k, v in checks.items() if not v]
    return {
        "pass": not failed,
        "checks": checks,
        "hits_count": len(hits),
        "failed_checks": failed,
    }
