# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/ws_registry.py
# @brief      Global registry of active WebSocket connections, keyed by user_id
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Global registry of active WebSocket connections, keyed by user_id.

Used by the HITL manager, the scheduler, the watchdog and the browser skill
to push real-time events to the user's open clients.

Multi-socket since 2026-06-10 (revue multi-utilisateurs, constat B-6): a
user may legitimately hold several connections at once (two tabs, PWA +
desktop, chat + voice). The previous ``dict[str, WebSocket]`` had two bugs:

1. a second connection silently *replaced* the first — pushes (HITL cards,
   scheduled-task results) only reached the most recent tab;
2. ``unregister(user_id)`` popped whichever socket was registered — so when
   the OLD tab closed, it deregistered the NEW tab's socket, leaving the
   user connected but unreachable.

Senders should use :func:`send_text_all` (fan-out, per-socket failures
swallowed and dead sockets pruned).
"""
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)
_registry: dict[str, set[WebSocket]] = {}


def register(user_id: str, ws: WebSocket) -> None:
    conns = _registry.setdefault(user_id, set())
    conns.add(ws)
    if len(conns) > 1:
        logger.debug("User %s now has %d WebSockets", user_id, len(conns))


def unregister(user_id: str, ws: WebSocket | None = None) -> None:
    """Remove ``ws`` from the user's connection set.

    ``ws`` is required to fix the two-tab bug (closing tab A must not
    deregister tab B). ``ws=None`` clears every socket for the user —
    only meant for tests/cleanup paths.
    """
    conns = _registry.get(user_id)
    if conns is None:
        return
    if ws is None:
        _registry.pop(user_id, None)
        logger.debug("Unregistered ALL WebSockets for user %s", user_id)
        return
    conns.discard(ws)
    if not conns:
        _registry.pop(user_id, None)
    logger.debug("Unregistered one WebSocket for user %s", user_id)


def get(user_id: str) -> WebSocket | None:
    """Return one of the user's sockets (arbitrary if several).

    Deprecated for senders — use :func:`send_text_all` so every open
    client receives the push. Kept for presence checks (``is connected?``).
    """
    conns = _registry.get(user_id)
    if not conns:
        return None
    return next(iter(conns))


def get_all(user_id: str) -> list[WebSocket]:
    return list(_registry.get(user_id) or ())


async def send_text_all(user_id: str, text: str) -> int:
    """Fan-out ``text`` to every socket of ``user_id``.

    Per-socket failures are swallowed and the dead socket is pruned, so a
    zombie tab never blocks delivery to the others. Returns the number of
    sockets successfully written to.
    """
    delivered = 0
    for ws in get_all(user_id):
        try:
            await ws.send_text(text)
            delivered += 1
        except Exception:
            unregister(user_id, ws)
    return delivered
