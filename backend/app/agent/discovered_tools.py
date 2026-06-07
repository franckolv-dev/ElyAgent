# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/discovered_tools.py
# @brief      Per-conversation registry of tools surfaced via find_tool.
# @license    Elastic License 2.0
# =============================================================================
"""Per-conversation registry of tools the model discovered via ``find_tool``.

When the agent calls ``find_tool("…")`` and gets matches, the matched tool
names are recorded here keyed by ``conversation_id``. ``agent_node`` unions
them into the bound toolset on every subsequent turn of that conversation —
**sticky**, so the prompt-cache prefix re-warms once, then stays stable.

This is the runtime half of the "tool discovery is a tool" safety net: the
bound profile stays lean (cache-friendly) while the model can pull in any of
the ~180 catalog tools on demand. Makes the recurring "I have no tool for X"
failure (almost always a binding gap, not a real gap) self-healing.
"""
from __future__ import annotations

import logging
import threading
from typing import Final

logger = logging.getLogger(__name__)

_MAXSIZE: Final[int] = 1000  # bound the registry (one entry per conversation)
_lock = threading.Lock()
_registry: dict[str, set[str]] = {}


def add_discovered(conversation_id: str, names: list[str]) -> None:
    """Record tool names discovered in a conversation (idempotent, bounded)."""
    if not conversation_id or not names:
        return
    with _lock:
        bucket = _registry.setdefault(conversation_id, set())
        bucket.update(names)
        # FIFO-ish eviction so a long-running server doesn't grow unbounded.
        while len(_registry) > _MAXSIZE:
            _registry.pop(next(iter(_registry)))


def get_discovered(conversation_id: str) -> set[str]:
    """Tool names discovered so far in ``conversation_id`` (copy)."""
    if not conversation_id:
        return set()
    with _lock:
        return set(_registry.get(conversation_id, set()))


def discard_discovered(conversation_id: str) -> None:
    """Forget a conversation's discovered tools (e.g. on conversation close)."""
    with _lock:
        _registry.pop(conversation_id, None)
