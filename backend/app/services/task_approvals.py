# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/task_approvals.py
# @brief      Ephemeral, per-conversation "allow this tool for the rest of
#             this task" HITL approvals.
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Task-scoped HITL approvals (Franck, 2026-06-03).

Problem: during a Drive reorg the agent issued 11 ``drive_delete_file``
calls, one per file_id. ``drive_delete_file`` is in ``LOCKED_HITL_TOOLS``,
so the persistent "Toujours autoriser" preference is ignored and every
call re-prompted — 11 clicks for one approved task.

Fix: a third HITL level between "allow once" and "always allow" —
**"allow for this task"**. It approves the *tool/action* (NOT the
tool+args), for the rest of the *current conversation*, and:

  - works even for ``LOCKED_HITL_TOOLS`` (it's the user's explicit,
    ephemeral consent within a task they're actively driving);
  - is keyed by ``tool_name`` only — the file_id / email / etc. is
    irrelevant, so one click covers every later call of that tool;
  - is **in-memory only, never persisted** — it cannot leak into a
    different task/conversation, and a restart wipes it. (Permanent
    cross-task allow stays a separate, explicit opt-in via Settings →
    HITL preferences / the ``allow_always`` decision.)

Scope = conversation_id (for chat, the conversation is the task). A
mission-scoped variant can key on mission_id later if needed.
"""
from __future__ import annotations

import threading

# {conversation_id: {tool_name, ...}}
_approvals: dict[str, set[str]] = {}
_lock = threading.Lock()


def approve_tool_for_task(conversation_id: str, tool_name: str) -> None:
    """Mark ``tool_name`` as approved for the rest of ``conversation_id``."""
    if not conversation_id or not tool_name:
        return
    with _lock:
        _approvals.setdefault(conversation_id, set()).add(tool_name)


def is_tool_approved_for_task(conversation_id: str, tool_name: str) -> bool:
    """True if the user already approved ``tool_name`` for this task. Keyed
    by tool name only — args (file_id, …) are intentionally ignored."""
    if not conversation_id or not tool_name:
        return False
    with _lock:
        return tool_name in _approvals.get(conversation_id, set())


def approved_tools_for_task(conversation_id: str) -> set[str]:
    """Snapshot of the tools approved for ``conversation_id`` (copy)."""
    with _lock:
        return set(_approvals.get(conversation_id, set()))


def clear_task_approvals(conversation_id: str) -> None:
    """Drop all task-scoped approvals for ``conversation_id`` (e.g. when the
    conversation ends). Idempotent."""
    with _lock:
        _approvals.pop(conversation_id, None)
