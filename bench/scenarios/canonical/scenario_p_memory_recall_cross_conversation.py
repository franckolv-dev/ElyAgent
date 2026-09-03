# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_p_memory_recall_cross_conversation.py
# @brief      Sprint 3.7.3 J3 — canonical scenario P : a SEMANTIC_USER fact is
#             user-scoped, not conversation-scoped. A fact learned in one
#             conversation must be recallable from a DIFFERENT conversation —
#             the whole point of the cognitive memory.
# @license    MIT
# =============================================================================
"""Canonical scenario P — cross-conversation memory recall."""
from __future__ import annotations

import uuid


NAME = "P — memory recall cross-conversation"
DESCRIPTION = (
    "A SEMANTIC_USER fact stored during conversation A is recalled by the "
    "MemoryRecallService when queried from conversation B — recall is keyed "
    "on user_id, never on conversation_id. Hermetic (Qdrant monkeypatched)."
)
TAGS = ["shallow"]


async def run() -> dict:
    # Same hermetic strategy as scenario F : the SemanticUserStore hits
    # Qdrant in prod, so we patch its read methods to an in-memory stash
    # keyed by user_id. The point under test is that recall() is
    # conversation-agnostic — the stash has NO notion of conversation,
    # mirroring how user-level facts actually persist across chats.
    from app.services.memory import MemoryType, get_memory_recall_service
    from app.services.memory.semantic_user_store import SemanticUserStore
    from bench.scenarios._base import from_checks

    uid = f"bench_p_{uuid.uuid4().hex[:8]}"
    fact = "L'utilisateur préfère voyager en train plutôt qu'en avion."

    # The fact was learned during "conversation A". The store is keyed by
    # user, so it carries no conversation_id — exactly the property we test.
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
        svc = get_memory_recall_service.__wrapped__()
        # Recall from "conversation B" — a brand new chat, different thread.
        hits_conv_b = await svc.recall(
            memory_type=MemoryType.SEMANTIC_USER,
            query="comment l'utilisateur aime-t-il voyager ?",
            user_id=uid,
            limit=5,
        )
        # And again from yet another "conversation C" — still the same user.
        hits_conv_c = await svc.recall(
            memory_type=MemoryType.SEMANTIC_USER,
            query="préférences de transport",
            user_id=uid,
            limit=5,
        )
    finally:
        SemanticUserStore.get_relevant_facts = orig_facts
        SemanticUserStore.get_preferences = orig_prefs

    checks = {
        "recalled_in_conv_b": bool(hits_conv_b) and any(fact in h.content for h in hits_conv_b),
        "recalled_in_conv_c": bool(hits_conv_c) and any(fact in h.content for h in hits_conv_c),
        "type_is_semantic_user": all(
            h.type == MemoryType.SEMANTIC_USER for h in (hits_conv_b + hits_conv_c)
        ),
    }
    return from_checks(
        checks,
        hits_b=len(hits_conv_b),
        hits_c=len(hits_conv_c),
    )
