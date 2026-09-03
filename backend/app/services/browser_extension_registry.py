# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/browser_extension_registry.py
# @brief      Registry of connected ELY browser extension instances, keyed by
#             user_id. The agent will use this to dispatch commands to the
#             user's browser (read DOM, click, fill, screenshot…).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""In-process registry mapping user_id → active browser-extension WebSocket.

Sprint 0 scope: registration, handshake metadata, simple lookup. Sprint 1+
will add a request/response correlation layer so an agent tool can send
a command and await the result asynchronously.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class BrowserExtensionConnection:
    user_id: str
    websocket: WebSocket
    extension_version: str = ""
    user_agent: str = ""
    initial_tab: Optional[dict[str, Any]] = None
    connected_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    # Pending commands awaiting a result envelope back from the extension.
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)


# Single-instance registry. Async-locked because multiple workers/coroutines
# may register or look up concurrently.
_lock = asyncio.Lock()
_connections: dict[str, BrowserExtensionConnection] = {}


async def register(conn: BrowserExtensionConnection) -> None:
    """Register a new connection, evicting any prior one for the same user."""
    async with _lock:
        old = _connections.pop(conn.user_id, None)
        if old is not None:
            try:
                await old.websocket.close(code=4000, reason="Replaced by newer connection")
            except Exception:
                pass
            logger.info(
                "[browser-ext] replaced previous connection for user=%s",
                conn.user_id,
            )
        _connections[conn.user_id] = conn
        logger.info(
            "[browser-ext] registered user=%s version=%s ua=%r",
            conn.user_id, conn.extension_version, conn.user_agent[:80],
        )


async def unregister(user_id: str, websocket: WebSocket) -> None:
    """Remove a connection if it still matches the given websocket."""
    async with _lock:
        existing = _connections.get(user_id)
        if existing is not None and existing.websocket is websocket:
            _connections.pop(user_id, None)
            # Cancel every pending future to free the agent code waiting on them.
            for fut in existing.pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("browser extension disconnected"))
            logger.info("[browser-ext] unregistered user=%s", user_id)


def get(user_id: str) -> Optional[BrowserExtensionConnection]:
    return _connections.get(user_id)


def is_connected(user_id: str) -> bool:
    return user_id in _connections


def connection_count() -> int:
    return len(_connections)


def touch(user_id: str) -> None:
    """Update last-seen timestamp on any traffic from the extension."""
    conn = _connections.get(user_id)
    if conn is not None:
        conn.last_seen = time.monotonic()
