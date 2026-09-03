# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/browser_extension.py
# @brief      Browser extension router — owns the /ws/browser-extension
#             socket used by the ELY Chrome extension to act in the user's
#             actual browser tab (read DOM, click, fill, screenshot, with
#             HITL approval gating every destructive action).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""ELY Browser Extension WebSocket endpoint.

Sprint 0 (current): handshake + read-only command dispatch.
Sprint 1: HITL-gated destructive actions (click/fill/navigate).

Protocol summary
----------------
1.  Extension opens WebSocket to /ws/browser-extension.
2.  Server accepts, waits up to 10 s for a JSON envelope of type `hello`
    carrying `jwt`, `extension_version`, `user_agent`, optional `initial_tab`.
3.  Server validates JWT (must be an `access` token belonging to an active user),
    closes 4001 if invalid, otherwise registers the connection and ACKs.
4.  From there the channel is bidirectional:
       - Server → Extension: command envelopes (see protocol.js CMD types).
       - Extension → Server: events (TAB_CHANGED, PAGE_NAVIGATED, PONG,
         HITL_DECISION) and `result` envelopes correlated by `id` with
         previously-sent commands.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth.jwt import decode_token
from app.database import async_session
from app.models.extension_token import ExtensionToken
from app.models.user import User
from app.routers.extension_tokens import TOKEN_PREFIX, hash_token
from app.services import browser_extension_registry as bext_registry

logger = logging.getLogger(__name__)

ws_router = APIRouter()
api_router = APIRouter()
router = api_router  # alias for backward-compat with main.py auto-discovery

# ---------------------------------------------------------------------------
# Rate limit on connection attempts (same pattern as /ws/desktop, SEC-15)
# ---------------------------------------------------------------------------
_ws_attempts: dict[str, list[float]] = defaultdict(list)
_ws_lock = Lock()
# Higher than /ws/desktop's 10/min because the browser extension service
# worker may legitimately reconnect a few times on token rotation or
# config edits in quick succession (matches the SW's backoff progression).
_WS_MAX_ATTEMPTS = 30
_WS_WINDOW_SEC = 60
_HANDSHAKE_TIMEOUT_SEC = 10


def _rate_check(ip: str) -> bool:
    now = time.monotonic()
    with _ws_lock:
        attempts = _ws_attempts[ip]
        _ws_attempts[ip] = [t for t in attempts if now - t < _WS_WINDOW_SEC]
        if len(_ws_attempts[ip]) >= _WS_MAX_ATTEMPTS:
            return False
        _ws_attempts[ip].append(now)
        return True


# ---------------------------------------------------------------------------
# /ws/browser-extension
# ---------------------------------------------------------------------------

@ws_router.websocket("/browser-extension")
async def websocket_browser_extension(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"
    if not _rate_check(client_ip):
        await websocket.accept()
        await websocket.close(code=4029, reason="Too many connection attempts")
        logger.warning("[browser-ext] rate limit exceeded for %s", client_ip)
        return

    await websocket.accept()
    logger.debug("[browser-ext] connection accepted, waiting for hello…")

    # Wait for HELLO envelope carrying the JWT.
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=_HANDSHAKE_TIMEOUT_SEC,
        )
        env = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("[browser-ext] handshake malformed: %s", exc)
        await websocket.close(code=1008, reason="Bad handshake")
        return

    if env.get("type") != "hello":
        logger.warning("[browser-ext] first envelope was %r, expected 'hello'", env.get("type"))
        await websocket.close(code=4001, reason="Expected hello first")
        return

    payload: dict[str, Any] = env.get("payload") or {}
    token = payload.get("jwt", "") or payload.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    user_id: str | None = None
    auth_method: str = ""
    ext_token_row: ExtensionToken | None = None

    if token.startswith(TOKEN_PREFIX):
        # ── Long-lived extension token path (Sprint 0.5) ─────────────────
        # No expiry; the user revokes it from the web Settings UI when
        # they're done. We look up the row by SHA-256 hash so the plaintext
        # never sits in the database.
        digest = hash_token(token)
        async with async_session() as db:
            row = (await db.execute(
                select(ExtensionToken).where(ExtensionToken.token_hash == digest)
            )).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                await websocket.close(code=4001, reason="Invalid or revoked extension token")
                return
            # Touch last_used_at so the user can spot dormant tokens in
            # Settings and revoke them.
            row.last_used_at = datetime.utcnow()
            db.add(row)
            await db.commit()
            user_id = row.user_id
            ext_token_row = row
        auth_method = "extension_token"
    else:
        # ── Short-lived JWT path (legacy, still supported for the popup
        # quick-test flow). 60-minute expiry — fine for ad-hoc usage.
        decoded = decode_token(token)
        if not decoded or decoded.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id = decoded.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token payload")
            return
        auth_method = "jwt"

    # Look up the user to make sure they still exist and are active.
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
    if user is None:
        await websocket.close(code=4001, reason="User not found")
        return

    logger.info(
        "[browser-ext] auth ok user=%s method=%s token_name=%s",
        user_id, auth_method,
        ext_token_row.name if ext_token_row else "—",
    )

    # Register.
    conn = bext_registry.BrowserExtensionConnection(
        user_id=str(user_id),
        websocket=websocket,
        extension_version=str(payload.get("extension_version", "")),
        user_agent=str(payload.get("user_agent", "")),
        initial_tab=payload.get("initial_tab"),
    )
    await bext_registry.register(conn)

    # ACK back to the extension.
    try:
        await websocket.send_text(json.dumps({
            "v": "0.1.0",
            "type": "connected",
            "payload": {
                "user_id": str(user_id),
                "username": user.username,
            },
            "ts": int(time.time() * 1000),
        }))
    except Exception as e:
        logger.warning("[browser-ext] ack send failed: %s", e)
        await bext_registry.unregister(str(user_id), websocket)
        return

    # ── Read loop ───────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()
            bext_registry.touch(str(user_id))

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[browser-ext] non-JSON frame from user=%s", user_id)
                continue

            msg_type = msg.get("type")
            msg_id = msg.get("id")

            # Result envelope → resolve any pending future for this id.
            if msg_type == "result" and msg_id:
                fut = conn.pending.pop(msg_id, None)
                if fut is not None and not fut.done():
                    fut.set_result(msg.get("payload"))
                continue

            # Client-side heartbeat → respond with pong (keeps the WS
            # alive on idle and lets the extension verify backend liveness).
            if msg_type == "ping":
                try:
                    await websocket.send_text(json.dumps({
                        "v": "0.1.0",
                        "id": msg_id,
                        "type": "pong",
                        "payload": {},
                        "ts": int(time.time() * 1000),
                    }))
                except Exception:
                    pass
                continue

            # Events — sprint 0 just logs them. The agent layer (sprint 2+)
            # will subscribe to specific event streams (e.g. PAGE_NAVIGATED
            # to keep memory of recently visited pages).
            if msg_type in {"tab_changed", "page_navigated", "hitl_decision", "pong"}:
                logger.debug(
                    "[browser-ext] event user=%s type=%s payload=%s",
                    user_id, msg_type, json.dumps(msg.get("payload"))[:200],
                )
                continue

            logger.warning("[browser-ext] unknown message type=%r from user=%s", msg_type, user_id)

    except WebSocketDisconnect:
        logger.info("[browser-ext] disconnect user=%s", user_id)
    except Exception as e:
        logger.warning("[browser-ext] unexpected error user=%s: %s", user_id, e)
    finally:
        await bext_registry.unregister(str(user_id), websocket)


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

@api_router.get("/browser-extension/status")
async def browser_extension_status():
    """Tiny health endpoint usable by the website to show 'extension live'."""
    return {
        "connected_users": bext_registry.connection_count(),
    }
