# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_v_memory_types_routing.py
# @brief      Sprint 3.7.3 J4 — structural regression : Sprint 2.5 cognitive
#             memory typing. The 5 typed memories exist, parse leniently, and
#             MemoryRecallService routes per-type (SEMANTIC_USER returns typed
#             hits ; ERROR is write-only → []) and never raises.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario V — typed memory enum + per-type recall routing."""
from __future__ import annotations

import uuid


NAME = "V — memory 5-types + recall routing"
DESCRIPTION = (
    "MemoryType holds the 5 typed memories + AUTO, parse() is lenient, and "
    "recall routes per-type: SEMANTIC_USER returns SEMANTIC_USER-typed hits "
    "(Qdrant patched), ERROR is write-only (→ []), and recall never raises."
)
TAGS = ["shallow"]


async def run() -> dict:
    from app.services.memory import MemoryType, get_memory_recall_service
    from app.services.memory.semantic_user_store import SemanticUserStore
    from bench.scenarios._base import from_checks

    # 1. The 5 typed memories (+ AUTO fan-out) — the Sprint 2.5 backbone.
    expected = {
        "EPISODIC": "episodic",
        "SEMANTIC_USER": "semantic_user",
        "PROCEDURAL": "procedural",
        "ERROR": "error",
        "CONSTRAINT": "constraint",
    }
    enum_ok = all(
        getattr(MemoryType, k, None) is not None
        and MemoryType[k].value == v
        for k, v in expected.items()
    )
    auto_present = getattr(MemoryType, "AUTO", None) is not None

    # 2. Lenient parser : enum, lowercase, uppercase ; junk raises.
    parse_ok = (
        MemoryType.parse(MemoryType.EPISODIC) == MemoryType.EPISODIC
        and MemoryType.parse("semantic_user") == MemoryType.SEMANTIC_USER
        and MemoryType.parse("CONSTRAINT") == MemoryType.CONSTRAINT
    )
    parse_rejects_junk = False
    try:
        MemoryType.parse("not_a_type")
    except ValueError:
        parse_rejects_junk = True

    # 3. Per-type routing, hermetic (patch the Qdrant-backed store like F).
    uid = f"bench_v_{uuid.uuid4().hex[:8]}"
    fact = "L'utilisateur travaille sur le projet Ely."
    stash = {uid: [fact]}
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
        semantic_hits = await svc.recall(
            memory_type=MemoryType.SEMANTIC_USER, query="projet ?",
            user_id=uid, limit=5,
        )
        # ERROR is write-only in V1 → recall must return [] (no store call).
        error_hits = await svc.recall(
            memory_type=MemoryType.ERROR, query="boom", user_id=uid, limit=5,
        )
        # Never raises, even on an empty query.
        empty_hits = await svc.recall(
            memory_type=MemoryType.SEMANTIC_USER, query="   ",
            user_id=uid, limit=5,
        )
    finally:
        SemanticUserStore.get_relevant_facts = orig_facts
        SemanticUserStore.get_preferences = orig_prefs

    checks = {
        "five_types_present": enum_ok,
        "auto_present": auto_present,
        "parse_lenient": parse_ok,
        "parse_rejects_junk": parse_rejects_junk,
        "semantic_user_routed_typed": bool(semantic_hits)
        and all(h.type == MemoryType.SEMANTIC_USER for h in semantic_hits),
        "error_is_write_only": error_hits == [],
        "recall_never_raises_on_empty": empty_hits == [],
    }
    return from_checks(checks, semantic_hits=len(semantic_hits))
