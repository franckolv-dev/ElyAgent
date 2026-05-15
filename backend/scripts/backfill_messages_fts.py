#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/backfill_messages_fts.py
# @brief      One-time backfill of messages_fts from the existing messages
#             table. Sprint 1 — Memory recall.
#
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Backfill the messages_fts index from the existing messages table.

Usage from the project root — **note the `uv run --no-sync`**:

    docker compose exec backend uv run --no-sync python scripts/backfill_messages_fts.py

Why `uv run --no-sync` and not plain `python`?
    The ELY backend container installs dependencies into a `uv`-managed
    virtualenv at `/app/.venv/`. The bare `python` interpreter on PATH
    sees the system site-packages, not the venv → ``aiosqlite`` and
    other deps are missing. ``uv run --no-sync`` enters the venv without
    re-resolving the lock file (same convention as the container's
    main ``CMD``).

Local dev (outside Docker):

    cd backend && uv run python scripts/backfill_messages_fts.py

Idempotent: re-running won't create duplicates because we check the
current count and skip messages that are already indexed (matched by
message_id).

Batches of 1000 rows to keep memory bounded for large histories.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make sure we can import the `app` package whether this is run from
# scripts/ or from backend/ root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

import aiosqlite

from app.config import get_settings
from app.services.messages_fts_store import get_messages_fts_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
)
log = logging.getLogger("backfill")

_BATCH = 1000


def _db_path() -> str:
    url = get_settings().database_url
    return url.split("sqlite+aiosqlite:///")[-1]


async def _already_indexed_ids(db: aiosqlite.Connection) -> set[str]:
    """Return the set of message_ids already in messages_fts."""
    cursor = await db.execute("SELECT message_id FROM messages_fts")
    rows = await cursor.fetchall()
    return {r[0] for r in rows}


async def main() -> None:
    store = get_messages_fts_store()
    await store.init()

    db_path = _db_path()
    log.info("Backfilling messages_fts from %s", db_path)

    async with aiosqlite.connect(db_path) as db:
        # 1. Total count to log progress
        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        total = (await cursor.fetchone())[0]
        log.info("Total messages in DB: %d", total)

        already = await _already_indexed_ids(db)
        log.info("Already indexed: %d (will be skipped)", len(already))

        # 2. Stream messages JOIN conversations to fetch user_id in one go
        cursor = await db.execute(
            """
            SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                   c.user_id
            FROM   messages m
            JOIN   conversations c ON c.id = m.conversation_id
            ORDER BY m.created_at
            """
        )

        batch: list[dict] = []
        total_inserted = 0
        skipped_already = 0
        skipped_empty = 0

        async for row in cursor:
            mid, conv_id, role, content, created_at, user_id = row
            if mid in already:
                skipped_already += 1
                continue
            if not content or not content.strip() or role == "system":
                skipped_empty += 1
                continue
            # Convert created_at to epoch seconds. SQLite stores DateTime
            # columns as strings by default; aiosqlite returns them raw.
            try:
                from datetime import datetime
                if isinstance(created_at, str):
                    # SQLAlchemy default format: '2026-05-15 13:30:00.123456'
                    dt = datetime.fromisoformat(created_at.replace(" ", "T"))
                else:
                    dt = created_at
                ts = int(dt.timestamp())
            except Exception:
                ts = 0
            batch.append({
                "text": content,
                "message_id": mid,
                "conversation_id": conv_id,
                "user_id": user_id,
                "role": role,
                "created_at_ts": ts,
            })

            if len(batch) >= _BATCH:
                inserted = await store.index_batch(batch)
                total_inserted += inserted
                log.info(
                    "Batch inserted: %d (total %d / %d)",
                    inserted, total_inserted, total,
                )
                batch = []

        # Flush remaining
        if batch:
            inserted = await store.index_batch(batch)
            total_inserted += inserted

    log.info(
        "Backfill done. Inserted: %d, skipped (already indexed): %d, "
        "skipped (empty/system): %d", total_inserted, skipped_already,
        skipped_empty,
    )


if __name__ == "__main__":
    asyncio.run(main())
