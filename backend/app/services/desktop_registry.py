# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/desktop_registry.py
# @brief      Registry of active ELY Desktop daemon connections, keyed by user_id.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Registry of active ELY Desktop daemon connections, keyed by user_id.

Le tunnel Cloudflare reset périodiquement la WS du daemon (rotation des
connexions edge) ; le daemon se reconnecte en ~2 s. Ce module tolère ces
blips : ensure_connected() attend la reconnexion pendant une grâce, et
send_command() détecte le remplacement de connexion en cours de commande
pour re-tenter une fois sur la nouvelle.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Grâce accordée au daemon pour se reconnecter après un reset du tunnel
# Cloudflare (observé : ~2 s). Doit rester nettement sous le timeout de
# commande (30 s) pour qu'un vrai débranchement échoue en temps utile.
RECONNECT_GRACE = 15.0
_POLL_INTERVAL = 0.5


class DesktopNotConnectedError(RuntimeError):
    pass


class _ConnectionReplacedError(RuntimeError):
    """Interne : la connexion utilisée est morte ou a été remplacée."""


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
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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


def unregister(user_id: str, ws: WebSocket | None = None) -> None:
    """Unregister the user's connection.

    Si `ws` est fourni, ne désenregistre que si c'est encore CETTE connexion :
    quand le daemon se reconnecte avant que le vieux handler WS ne meure, le
    finally du vieux handler ne doit pas éjecter la connexion fraîche.
    """
    conn = _connections.get(user_id)
    if conn is None:
        return
    if ws is not None and conn.ws is not ws:
        logger.debug(
            "Desktop agent for user %s already replaced — stale unregister ignored",
            user_id,
        )
        return
    _connections.pop(user_id, None)
    logger.info("Desktop agent unregistered for user %s", user_id)


def get(user_id: str) -> DesktopConnection | None:
    return _connections.get(user_id)


def is_connected(user_id: str) -> bool:
    return user_id in _connections


async def ensure_connected(user_id: str, grace: float = RECONNECT_GRACE) -> bool:
    """Attend jusqu'à `grace` secondes que le daemon soit connecté.

    Rend un blip de reconnexion (~2 s après un reset Cloudflare) invisible
    pour l'appelant. Retourne False si le daemon n'est pas revenu à temps.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + grace
    while True:
        if is_connected(user_id):
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(_POLL_INTERVAL, remaining))


async def _wait_for_new_connection(
    user_id: str, old_conn: DesktopConnection, grace: float
) -> DesktopConnection | None:
    """Attend une connexion DIFFÉRENTE de `old_conn` (reconnexion effective)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + grace
    while True:
        conn = _connections.get(user_id)
        if conn is not None and conn is not old_conn:
            return conn
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(_POLL_INTERVAL, remaining))


async def _run_command(
    conn: DesktopConnection, user_id: str, cmd: str, args: dict, timeout: float
) -> dict:
    """Envoie une commande sur `conn` et attend son résultat.

    Lève _ConnectionReplacedError si le socket meurt à l'envoi ou si la
    connexion est remplacée/perdue pendant l'attente — l'attente se fait par
    tranches pour le détecter sans consommer le timeout de 30 s.
    """
    cmd_id = uuid.uuid4().hex[:8]
    event = asyncio.Event()
    conn._pending[cmd_id] = event

    try:
        payload = json.dumps({"cmd_id": cmd_id, "cmd": cmd, "args": args})
        try:
            await conn.ws.send_text(payload)
        except Exception as exc:  # socket mort : la commande n'est jamais partie
            raise _ConnectionReplacedError(str(exc)) from exc

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not event.is_set():
            if _connections.get(user_id) is not conn:
                raise _ConnectionReplacedError(
                    f"connection replaced while waiting for '{cmd}'"
                )
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise DesktopTimeoutError(
                    f"Desktop command '{cmd}' timed out after {timeout}s"
                )
            try:
                await asyncio.wait_for(
                    event.wait(), timeout=min(_POLL_INTERVAL, remaining)
                )
            except asyncio.TimeoutError:
                continue

        result = conn._results.pop(cmd_id, {})
        if result.get("status") == "error":
            raise DesktopCommandError(
                result.get("error", "Unknown error from desktop agent")
            )
        return result.get("result", {})
    finally:
        conn._pending.pop(cmd_id, None)
        conn._results.pop(cmd_id, None)


async def send_command(
    user_id: str,
    cmd: str,
    args: dict,
    timeout: float = 30.0,
    reconnect_grace: float = RECONNECT_GRACE,
) -> dict:
    conn = _connections.get(user_id)
    if not conn:
        if not await ensure_connected(user_id, grace=reconnect_grace):
            raise DesktopNotConnectedError(
                f"No desktop agent connected for user {user_id}"
            )
        conn = _connections[user_id]

    try:
        return await _run_command(conn, user_id, cmd, args, timeout)
    except _ConnectionReplacedError:
        # Reset du tunnel Cloudflare en cours de commande : on attend la
        # reconnexion du daemon et on re-tente UNE fois sur la nouvelle.
        logger.info(
            "Desktop connection lost during '%s' for user %s — waiting for "
            "reconnection (grace %.0fs)",
            cmd,
            user_id,
            reconnect_grace,
        )
        new_conn = await _wait_for_new_connection(user_id, conn, reconnect_grace)
        if new_conn is None:
            raise DesktopNotConnectedError(
                f"Desktop connection lost during '{cmd}' and did not come back "
                f"within {reconnect_grace:.0f}s"
            ) from None
        try:
            return await _run_command(new_conn, user_id, cmd, args, timeout)
        except _ConnectionReplacedError as exc:
            raise DesktopNotConnectedError(
                f"Desktop connection lost again while retrying '{cmd}': {exc}"
            ) from None


def deliver_result(user_id: str, message: dict) -> None:
    """Called by the WebSocket router when a result arrives from the daemon."""
    conn = _connections.get(user_id)
    if not conn:
        return
    cmd_id = message.get("cmd_id")
    if cmd_id and cmd_id in conn._pending:
        conn._results[cmd_id] = message
        conn._pending[cmd_id].set()
