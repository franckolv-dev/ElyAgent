"""Registry of active ELY Desktop daemon connections, keyed by user_id."""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class DesktopNotConnectedError(RuntimeError):
    pass


class DesktopCommandError(RuntimeError):
    pass


class DesktopTimeoutError(RuntimeError):
    pass


@dataclass
class DesktopConnection:
    user_id: str
    ws: WebSocket
    platform: str
    version: str
    sandbox_dirs: list[str]
    connected_at: datetime = field(default_factory=datetime.utcnow)
    _pending: dict[str, asyncio.Event] = field(default_factory=dict)
    _results: dict[str, dict] = field(default_factory=dict)


_connections: dict[str, DesktopConnection] = {}


def register(user_id: str, ws: WebSocket, handshake: dict) -> DesktopConnection:
    conn = DesktopConnection(
        user_id=user_id,
        ws=ws,
        platform=handshake.get("platform", "unknown"),
        version=handshake.get("version", "unknown"),
        sandbox_dirs=handshake.get("sandbox_dirs", []),
    )
    _connections[user_id] = conn
    logger.info(
        "Desktop agent registered for user %s (platform=%s)", user_id, conn.platform
    )
    return conn


def unregister(user_id: str) -> None:
    if _connections.pop(user_id, None) is not None:
        logger.info("Desktop agent unregistered for user %s", user_id)


def get(user_id: str) -> DesktopConnection | None:
    return _connections.get(user_id)


def is_connected(user_id: str) -> bool:
    return user_id in _connections


async def send_command(
    user_id: str, cmd: str, args: dict, timeout: float = 30.0
) -> dict:
    conn = _connections.get(user_id)
    if not conn:
        raise DesktopNotConnectedError(
            f"No desktop agent connected for user {user_id}"
        )

    cmd_id = uuid.uuid4().hex[:8]
    event = asyncio.Event()
    conn._pending[cmd_id] = event

    try:
        payload = json.dumps({"cmd_id": cmd_id, "cmd": cmd, "args": args})
        await conn.ws.send_text(payload)
        await asyncio.wait_for(event.wait(), timeout=timeout)
        result = conn._results.pop(cmd_id, {})
        if result.get("status") == "error":
            raise DesktopCommandError(
                result.get("error", "Unknown error from desktop agent")
            )
        return result.get("result", {})
    except asyncio.TimeoutError:
        raise DesktopTimeoutError(
            f"Desktop command '{cmd}' timed out after {timeout}s"
        )
    finally:
        conn._pending.pop(cmd_id, None)
        conn._results.pop(cmd_id, None)


def deliver_result(user_id: str, message: dict) -> None:
    """Called by the WebSocket router when a result arrives from the daemon."""
    conn = _connections.get(user_id)
    if not conn:
        return
    cmd_id = message.get("cmd_id")
    if cmd_id and cmd_id in conn._pending:
        conn._results[cmd_id] = message
        conn._pending[cmd_id].set()
