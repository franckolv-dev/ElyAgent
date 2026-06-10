# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/sqlite_aio.py
# @brief      Connexions aiosqlite hors-engine alignées sur les pragmas de
#             l'engine SQLAlchemy (revue multi-utilisateurs 2026-06-10, B-2).
# @license    Elastic License 2.0
# =============================================================================
"""Out-of-engine aiosqlite connections with the SAME pragmas as the engine.

The FTS stores open raw ``aiosqlite.connect()`` connections on the same
``cyberentity.db`` file as the SQLAlchemy engine. Before 2026-06-10 those
connections used the sqlite3 defaults: **5 s** lock timeout (vs 30 s on the
engine) and ``synchronous=FULL`` (fsync on every commit). Under concurrent
writers, an FTS write waiting more than 5 s got ``database is locked`` and
— the writes being "best-effort, never raises" — **the index row was lost
forever, silently**: memory recall and message search degraded per-user in
a non-reproducible way. The FULL fsyncs also widened everyone's lock
windows for nothing.

Single fix point: every out-of-engine connection goes through
:func:`connect`, which applies ``timeout=30`` + ``busy_timeout=30000`` +
``synchronous=NORMAL`` — mirroring ``database.py``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import aiosqlite

_BUSY_TIMEOUT_MS = 30_000


@asynccontextmanager
async def connect(path: str):
    """``async with connect(path) as db:`` — aiosqlite with engine pragmas."""
    async with aiosqlite.connect(path, timeout=30) as db:
        # Curseurs PRAGMA fermés immédiatement — un curseur ouvert qui
        # traîne bloque les opérations exclusives (VACUUM, etc.).
        await (await db.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")).close()
        await (await db.execute("PRAGMA synchronous=NORMAL")).close()
        yield db
