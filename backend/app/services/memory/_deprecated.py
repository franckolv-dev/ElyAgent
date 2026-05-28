# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/_deprecated.py
# @brief      Sprint 2.5 Jalon 7 — helper for tools wrapped as legacy aliases
#             of `memory_recall`. Logs a one-shot deprecation per process.
# @license    Elastic License 2.0
# =============================================================================
"""One-shot deprecation logger for legacy memory tools.

Each tool listed in ``app/services/memory/ROUTING.md`` as "deprecated"
calls :py:func:`log_deprecation` at entry. The first call logs a
``DeprecationWarning`` line; subsequent calls are silent to avoid log
spam. After Sprint 2.5 V2 we remove these wrappers entirely and the
LLM-facing tool name disappears.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


_warned: set[str] = set()
_lock = threading.Lock()


def log_deprecation(tool_name: str, *, successor: str = "memory_recall") -> None:
    """Log a one-shot deprecation notice for *tool_name*.

    Args:
        tool_name: the LangChain tool name being deprecated.
        successor: the new tool name to use instead. Default: ``memory_recall``.
    """
    with _lock:
        if tool_name in _warned:
            return
        _warned.add(tool_name)
    logger.warning(
        "DEPRECATION — tool %r is a legacy alias and will be removed in Sprint 2.5 V2. "
        "New code should call %r instead. See app/services/memory/ROUTING.md.",
        tool_name,
        successor,
    )


def _reset_for_tests() -> None:
    """Test-only: clear the once-per-process state so a test can assert
    that the warning is emitted again."""
    with _lock:
        _warned.clear()
