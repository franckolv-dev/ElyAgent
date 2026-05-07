# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/app/services/frozen_memory.py
# @brief      Frozen memory snapshot per conversation (Hermes Chantier 2)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Frozen memory snapshot — Hermes Chantier 2.

Why
---
The user's memory blocks (``🧠 user_profile``, ``💾 mémorisé``,
``🔁 interactions passées``, ``👤 préférences``, ``🛡️ contraintes``)
are queried at every turn from Qdrant + SQL. Beyond the latency cost,
the **content can drift between turns** even when the user hasn't done
anything meaningful — Qdrant similarity search returns slightly
different ranks across calls, especially for short queries. This was
silently breaking the prompt cache prefix : a single token difference
in the memory block at turn 5 invalidated the entire prefix and
re-tokenized everything before that point.

Hermes solves this by reading user memory **once** at session start,
freezing the resulting snapshot, and using that snapshot for every
turn until the session ends. New facts written via ``memory_archive``
or ``save_user_preference`` mid-session DO get persisted to Qdrant /
SQL — they just don't appear in the model's prompt until the *next*
session, when the snapshot is rebuilt.

Trade-off
---------
- ✅ Prompt cache prefix preserved → −75 % latency, −90 % cost on
  cacheable tokens after turn 1
- ✅ Model "attention" stays anchored on the same memory tokens turn
  after turn → less context shuffling, more consistent behaviour
- ⚠️ A fact archived at turn 2 won't appear in the 🧠 block at turn 3
  — but it IS visible to the model via the conversation history
  (the user said it, the assistant replied, those messages are in
  ``messages``). And it surfaces back in the 🧠 block of the *next*
  conversation. Acceptable for the cache benefit.

API surface
-----------
``get_or_build(conversation_id, user_id, builder)`` — async wrapper
that calls ``builder`` only once per conversation. ``invalidate`` and
``discard`` mirror ``system_prompt_cache``.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Awaitable, Callable, Final, Optional

logger = logging.getLogger(__name__)


_MAX_ENTRIES: Final[int] = 1000


class _BoundedDict(OrderedDict):
    """OrderedDict with FIFO eviction beyond ``maxsize``."""

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value) -> None:  # type: ignore[override]
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)


# conversation_id → {"snapshot": str, "user_id": str, "built_at": float}
_snapshots: _BoundedDict = _BoundedDict(maxsize=_MAX_ENTRIES)


async def get_or_build(
    conversation_id: str,
    user_id: str,
    builder: Callable[[], Awaitable[str]],
) -> str:
    """Return the frozen memory snapshot for a conversation.

    On the first call, awaits ``builder`` to produce the snapshot string
    (a multi-section block with 🧠 user_profile, preferences, constraints,
    memories, past_interactions). On subsequent calls, returns the same
    cached string regardless of any memory updates that happened since.

    Parameters
    ----------
    conversation_id
        Unique conversation identifier. Empty string bypasses the cache
        (always rebuilds).
    user_id
        Stored alongside the snapshot for diagnostics. NOT used as part
        of the cache key — the assumption is that one conversation =
        one user. If an admin impersonation tool ever spoofed user_id
        mid-conversation, the snapshot would still reflect the original
        user. Considered acceptable.
    builder
        Async zero-arg function that returns the snapshot string. Called
        at most once per ``conversation_id`` until invalidation.
    """
    if not conversation_id:
        return await builder()

    entry = _snapshots.get(conversation_id)
    if entry is not None:
        logger.debug("frozen_memory: HIT conv=%s", conversation_id)
        return entry["snapshot"]

    snapshot = await builder()
    if not isinstance(snapshot, str):
        logger.warning(
            "frozen_memory: builder returned non-str (%s) — bypassing cache",
            type(snapshot).__name__,
        )
        return str(snapshot) if snapshot is not None else ""

    _snapshots[conversation_id] = {
        "snapshot": snapshot,
        "user_id": user_id,
        "built_at": time.time(),
    }
    logger.info(
        "frozen_memory: BUILD conv=%s user=%s (%d chars)",
        conversation_id, user_id[:8] if user_id else "?", len(snapshot),
    )
    return snapshot


def invalidate(conversation_id: str) -> None:
    """Drop the snapshot for ``conversation_id``."""
    if conversation_id in _snapshots:
        _snapshots.pop(conversation_id, None)
        logger.info("frozen_memory: INVALIDATE conv=%s", conversation_id)


def discard(conversation_id: str) -> None:
    """Drop the snapshot (call on WS disconnect)."""
    if conversation_id in _snapshots:
        _snapshots.pop(conversation_id, None)
        logger.debug("frozen_memory: DISCARD conv=%s", conversation_id)


def snapshot_size() -> int:
    """Total number of conversations with a frozen snapshot."""
    return len(_snapshots)


def _reset_for_tests() -> None:
    """Test-only helper. Never call from production code."""
    _snapshots.clear()
