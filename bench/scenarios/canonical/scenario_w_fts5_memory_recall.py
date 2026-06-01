# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_w_fts5_memory_recall.py
# @brief      Sprint 3.7.3 J4 — structural regression : Sprint 1 SQLite FTS5
#             keyword index over memory text. store → search round-trip
#             returns the indexed qdrant_id, with per-user isolation. Fully
#             end-to-end (FTS5 is SQLite-native, no Qdrant needed).
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario W — FTS5 memory keyword recall round-trip."""
from __future__ import annotations

import uuid


NAME = "W — FTS5 memory keyword recall"
DESCRIPTION = (
    "store() indexes a memory's text + qdrant_id ; search() returns that "
    "qdrant_id by BM25 keyword match (accent-insensitive) ; a different user "
    "gets nothing (isolation). Native SQLite FTS5, no Qdrant."
)
TAGS = ["shallow"]


async def run() -> dict:
    from app.services.fts_store import get_fts_store
    from bench.scenarios._base import from_checks

    uid = f"bench_w_{uuid.uuid4().hex[:8]}"
    other_uid = f"bench_w_other_{uuid.uuid4().hex[:8]}"
    collection = "interactions"
    qdrant_id = f"qid-{uuid.uuid4().hex[:8]}"
    text = "Le projet Ely repose sur une mémoire cognitive typée et locale."

    store = get_fts_store()
    try:
        await store.init()  # idempotent CREATE VIRTUAL TABLE IF NOT EXISTS
        await store.store(
            text=text, user_id=uid, collection=collection, qdrant_id=qdrant_id
        )

        # Keyword hit (accent-insensitive thanks to remove_diacritics).
        hits = await store.search(
            query="memoire cognitive", user_id=uid, collection=collection
        )
        # Non-matching keyword → no hit.
        miss = await store.search(
            query="astrophysique quantique", user_id=uid, collection=collection
        )
        # Isolation : another user must not see this entry.
        foreign = await store.search(
            query="memoire cognitive", user_id=other_uid, collection=collection
        )

        checks = {
            "stored_id_recalled": qdrant_id in hits,
            "non_matching_query_empty": miss == [],
            "cross_user_isolated": qdrant_id not in foreign,
        }
        return from_checks(checks, hits=len(hits), qdrant_id=qdrant_id)
    finally:
        await store.delete_user_data(uid)
        await store.delete_user_data(other_uid)
