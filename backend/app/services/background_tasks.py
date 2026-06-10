# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/background_tasks.py
# @brief      Strong-referenced fire-and-forget task spawner
#             (revue multi-utilisateurs 2026-06-10, §4 mineurs).
# @license    Elastic License 2.0
# =============================================================================
"""Strong-referenced fire-and-forget task spawner.

``asyncio.create_task(...)`` only gives the event loop a WEAK reference to
the task: if the caller drops the returned handle (the classic
fire-and-forget idiom), the task can be garbage-collected mid-flight and
silently never complete. In ELY that meant learning signals, memory
extraction and FTS indexing could vanish under GC pressure — invisible in
mono-user, measurable with N users.

Pattern lifted from ``agent/sub_agents/factory.py`` (``_bg_tasks``), which
documented the hazard first; this module centralises it so every
fire-and-forget site uses the same registry and gets exception logging for
free.

Usage::

    from app.services.background_tasks import spawn
    spawn(record_signal(...), label="learning.hitl_refusal")
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_BG_TASKS: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, label: str | None = None) -> asyncio.Task:
    """Schedule ``coro`` with a strong reference held until completion.

    Exceptions are logged (warning) instead of disappearing with the task.
    ``label`` defaults to the coroutine's qualname so drop-in replacements
    of bare ``asyncio.create_task(...)`` keep a meaningful name for free.
    Returns the task for callers that want to await/cancel it anyway.
    """
    resolved = label or getattr(coro, "__qualname__", None) or "bg"
    task = asyncio.create_task(coro, name=resolved)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("Background task %r failed: %s", resolved, exc)

    task.add_done_callback(_done)
    return task


def pending_count() -> int:
    """Number of in-flight background tasks (observability helper)."""
    return len(_BG_TASKS)
