#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/wipe_memory_for_sprint_2_5.py
# @brief      Sprint 2.5 Jalon 5 — clean slate for the cognitive memory.
#             Snapshots every Qdrant collection (server-side), then wipes
#             all memory data so V1 starts from a structurally clean base.
#
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Clean slate for the typed memory subpackage — Sprint 2.5 Jalon 5.

Why a clean slate (decided 2026-05-21 with Franck)
---------------------------------------------------
The 799 entries currently in the `memories` Qdrant collection accumulated
under several known structural bugs that the Sprint 2.5 architecture
explicitly fixes :

  - 725/799 entries are missing the `category` payload field
  - Mix of float Unix ts and ISO 8601 string on `created_at`
  - No deduplication before 2026-05-09 — duplicates likely present
  - Hallucinated self-limitations stored as security_constraints
    before _looks_like_self_limitation guard (2026-05-06)
  - Bench sessions + agent test traces interleaved with real memories

Migrating 799 entries via a heuristic classifier would yield ~70%
precision, leaving ~250 mis-classified rows flagged `migrated_uncertain`
that would pollute the future Sprint 2.5 §4 maintenance cron. Franck
chose to wipe and let the new typed stores re-build memory cleanly
from natural usage (the maintenance agent in Jalon 6 will do that
automatically as soon as it lands).

What is wiped
-------------
Qdrant collections   : memories, user_profile, security_constraints,
                       interactions (created if missing). The new
                       `procedures` collection is left empty (Jalon 1
                       just created it).
SQL tables           : user_memory_logs, user_profiles
SQLite FTS5 rows     : memory_fts WHERE collection IN (...)

What is preserved
-----------------
Users + conversations + messages + messages_fts + notes + user_vocabulary
+ learned_routing_keyword + every non-memory table. Franck's identity
and conversational history stay intact — only the typed memory layer
restarts.

Safety net
----------
A Qdrant snapshot is taken **before** each collection is recreated.
Snapshots live server-side under `/qdrant/storage/snapshots/<collection>/`
and can be restored manually via the Qdrant HTTP API. See the docstring
of `_snapshot_collection` for the recovery command.

Usage
-----
Dry-run (default — prints what would happen, touches nothing) ::

    cd backend && uv run python scripts/wipe_memory_for_sprint_2_5.py

Live run (snapshot + wipe, irreversible without restoring snapshots) ::

    cd backend && uv run python scripts/wipe_memory_for_sprint_2_5.py --confirm
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.services.memory._constants import (
    COLLECTION_CONSTRAINTS,
    COLLECTION_INTERACTIONS,
    COLLECTION_MEMORIES,
    COLLECTION_PREFERENCES,
    COLLECTION_PROCEDURES,
    VECTOR_DIM,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
)
log = logging.getLogger("wipe")


# Order matters only for log readability. Procedures is included so it
# exists empty at the end of the run if it wasn't already created.
_COLLECTIONS_TO_WIPE: tuple[str, ...] = (
    COLLECTION_MEMORIES,
    COLLECTION_PREFERENCES,
    COLLECTION_CONSTRAINTS,
    COLLECTION_INTERACTIONS,
    COLLECTION_PROCEDURES,
)


# ──────────────────────────────────────────────────────────────────────
# Qdrant operations
# ──────────────────────────────────────────────────────────────────────


def _qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=get_settings().qdrant_url)


def _count_collection(client, name: str) -> int | None:
    """Return the point count of *name*, or None if the collection doesn't exist."""
    try:
        info = client.get_collection(name)
    except Exception:
        return None
    # qdrant-client surfaces this as either `info.points_count` (>=v1.7)
    # or `info.vectors_count` on older versions. Try both.
    return getattr(info, "points_count", None) or getattr(info, "vectors_count", 0)


def _snapshot_collection(client, name: str) -> str | None:
    """Create a server-side snapshot of *name*. Returns snapshot filename.

    Recovery command (run inside the Qdrant container later if needed)::

        POST http://qdrant:6333/collections/<name>/snapshots/recover
        Content-Type: application/json
        {"location": "file:///qdrant/storage/snapshots/<name>/<filename>"}

    A snapshot of an empty/missing collection is skipped (no payload to
    save).
    """
    if _count_collection(client, name) in (None, 0):
        log.info("  snapshot skipped (%s is empty or missing)", name)
        return None
    try:
        snap = client.create_snapshot(collection_name=name)
        # qdrant-client returns a `SnapshotDescription` with a `.name` field.
        snap_name = getattr(snap, "name", str(snap))
        log.info("  snapshot OK : %s/%s", name, snap_name)
        return snap_name
    except Exception as exc:
        log.error("  snapshot FAILED for %s : %s", name, exc)
        # Hard fail — we never wipe without a backup.
        raise


def _recreate_collection(client, name: str) -> None:
    from qdrant_client.models import Distance, VectorParams
    try:
        client.delete_collection(name)
        log.info("  deleted    %s", name)
    except Exception as exc:
        log.warning("  delete skipped for %s : %s", name, exc)
    client.create_collection(
        name,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    log.info("  recreated  %s  (empty, dim=%d)", name, VECTOR_DIM)


# ──────────────────────────────────────────────────────────────────────
# SQL operations
# ──────────────────────────────────────────────────────────────────────


_SQL_TABLES_TO_TRUNCATE = ("user_memory_logs", "user_profiles")


async def _truncate_sql_tables(dry_run: bool) -> dict[str, int]:
    """Count rows in the memory SQL tables, optionally delete them."""
    from sqlalchemy import text as sql
    from app.database import async_session

    counts: dict[str, int] = {}
    async with async_session() as session:
        for table in _SQL_TABLES_TO_TRUNCATE:
            try:
                res = await session.execute(sql(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = res.scalar_one()
            except Exception as exc:
                log.warning("  count failed for %s : %s", table, exc)
                counts[table] = -1
        if not dry_run:
            for table in _SQL_TABLES_TO_TRUNCATE:
                if counts.get(table, 0) > 0:
                    await session.execute(sql(f"DELETE FROM {table}"))
                    log.info("  truncated  %s  (%d rows)", table, counts[table])
            await session.commit()
    return counts


# ──────────────────────────────────────────────────────────────────────
# FTS5 cleanup
# ──────────────────────────────────────────────────────────────────────


async def _wipe_fts_rows(dry_run: bool) -> int:
    """Delete memory_fts rows whose `collection` is one we just wiped.

    messages_fts (Sprint 1 cross-conversation recall) is left untouched
    because it indexes the `messages` SQL table, which we keep.
    """
    import aiosqlite

    db_url = get_settings().database_url
    db_path = db_url.split("sqlite+aiosqlite:///")[-1]
    placeholders = ",".join("?" for _ in _COLLECTIONS_TO_WIPE)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            f"SELECT COUNT(*) FROM memory_fts WHERE collection IN ({placeholders})",
            tuple(_COLLECTIONS_TO_WIPE),
        )
        row = await cur.fetchone()
        count = (row or [0])[0]
        log.info("  memory_fts rows to wipe : %d", count)
        if not dry_run and count > 0:
            await db.execute(
                f"DELETE FROM memory_fts WHERE collection IN ({placeholders})",
                tuple(_COLLECTIONS_TO_WIPE),
            )
            await db.commit()
            log.info("  memory_fts wiped")
    return count


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


async def _amain(dry_run: bool) -> None:
    log.info(
        "Sprint 2.5 Jalon 5 — clean slate %s",
        "(DRY-RUN — no changes will be applied)" if dry_run else "(LIVE)",
    )

    client = _qdrant_client()

    # 1) Inventory
    log.info("Current state :")
    counts_before: dict[str, int] = {}
    for coll in _COLLECTIONS_TO_WIPE:
        c = _count_collection(client, coll)
        counts_before[coll] = c if c is not None else 0
        suffix = "" if c is not None else "  (collection does not exist)"
        log.info("  qdrant  %-22s = %s%s", coll, counts_before[coll], suffix)

    fts_count = await _wipe_fts_rows(dry_run=True)
    sql_counts = await _truncate_sql_tables(dry_run=True)
    for table, n in sql_counts.items():
        log.info("  sql     %-22s = %s rows", table, n)
    log.info("  fts5    memory_fts (relevant rows) = %s", fts_count)

    if dry_run:
        log.info(
            "Dry-run complete. Re-run with --confirm to snapshot + wipe."
        )
        return

    # 2) Snapshot every non-empty collection (hard-fails on snapshot error)
    log.info("Taking Qdrant snapshots (safety net) :")
    for coll in _COLLECTIONS_TO_WIPE:
        _snapshot_collection(client, coll)

    # 3) Wipe SQL + FTS first (faster, lower failure cost)
    log.info("Wiping SQL memory tables :")
    await _truncate_sql_tables(dry_run=False)
    log.info("Wiping FTS5 memory rows :")
    await _wipe_fts_rows(dry_run=False)

    # 4) Recreate Qdrant collections empty
    log.info("Recreating Qdrant collections empty :")
    for coll in _COLLECTIONS_TO_WIPE:
        _recreate_collection(client, coll)

    # 5) Re-inventory
    log.info("Final state :")
    for coll in _COLLECTIONS_TO_WIPE:
        c = _count_collection(client, coll)
        log.info("  qdrant  %-22s = %s", coll, c if c is not None else "missing")
    sql_counts_after = await _truncate_sql_tables(dry_run=True)
    for table, n in sql_counts_after.items():
        log.info("  sql     %-22s = %s rows", table, n)

    log.info("Clean slate complete — Sprint 2.5 V1 can be used from a clean state.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot + wipe ELY's typed memory stores (Sprint 2.5 Jalon 5)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Actually perform the wipe. Without this flag the script is "
            "a dry-run and only prints the inventory."
        ),
    )
    args = parser.parse_args()
    asyncio.run(_amain(dry_run=not args.confirm))


if __name__ == "__main__":
    main()
