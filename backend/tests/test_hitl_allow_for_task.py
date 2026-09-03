# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_allow_for_task.py
# @brief      2026-06-03 — pin the task-scoped "Autoriser pour cette tâche"
#             HITL level: the ephemeral per-conversation approval store, the
#             tool_node wiring (check before prompt + allow_for_task handler),
#             and the REST route.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for the third HITL level — "allow for this task".

Context (Franck, 2026-06-03): a Drive reorg issued 11 drive_delete_file
calls (one per file_id). drive_delete_file is LOCKED, so "Toujours
autoriser" was ignored and every call re-prompted — 11 clicks. The fix:
approve the *action* (tool_name, args-agnostic) for the rest of the
*current conversation*, ephemeral, bypassing the lock, NOT persisted.
"""
from __future__ import annotations

from pathlib import Path

from app.services.task_approvals import (
    approve_tool_for_task,
    approved_tools_for_task,
    clear_task_approvals,
    is_tool_approved_for_task,
)

_BACKEND = Path(__file__).resolve().parents[1]
_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


# ── ephemeral store behaviour (the core fix) ──────────────────────────────────


def test_approve_then_approved_for_same_tool() -> None:
    conv = "conv-A"
    clear_task_approvals(conv)
    assert is_tool_approved_for_task(conv, "drive_delete_file") is False
    approve_tool_for_task(conv, "drive_delete_file")
    assert is_tool_approved_for_task(conv, "drive_delete_file") is True
    clear_task_approvals(conv)


def test_approval_is_args_agnostic_by_construction() -> None:
    """The store is keyed by tool_name only — there is no args parameter, so
    one approval covers every later call of that tool regardless of file_id.
    This is the whole point (11 deletes → 1 click)."""
    conv = "conv-args"
    clear_task_approvals(conv)
    approve_tool_for_task(conv, "drive_delete_file")
    # whatever the file_id, the same tool stays approved
    assert is_tool_approved_for_task(conv, "drive_delete_file") is True
    assert is_tool_approved_for_task(conv, "drive_delete_file") is True
    clear_task_approvals(conv)


def test_scoped_per_conversation() -> None:
    clear_task_approvals("conv-1")
    clear_task_approvals("conv-2")
    approve_tool_for_task("conv-1", "drive_move_file")
    assert is_tool_approved_for_task("conv-1", "drive_move_file") is True
    # a different conversation/task is NOT approved → not permanent across tasks
    assert is_tool_approved_for_task("conv-2", "drive_move_file") is False
    clear_task_approvals("conv-1")


def test_distinct_tools_isolated() -> None:
    conv = "conv-tools"
    clear_task_approvals(conv)
    approve_tool_for_task(conv, "drive_delete_file")
    assert is_tool_approved_for_task(conv, "drive_move_file") is False
    clear_task_approvals(conv)


def test_clear_removes_approvals() -> None:
    conv = "conv-clear"
    approve_tool_for_task(conv, "drive_delete_file")
    clear_task_approvals(conv)
    assert is_tool_approved_for_task(conv, "drive_delete_file") is False
    assert approved_tools_for_task(conv) == set()


def test_empty_inputs_are_safe_noops() -> None:
    approve_tool_for_task("", "drive_delete_file")  # no crash
    approve_tool_for_task("conv", "")
    assert is_tool_approved_for_task("", "x") is False
    assert is_tool_approved_for_task("conv", "") is False


def test_snapshot_is_a_copy() -> None:
    conv = "conv-snap"
    clear_task_approvals(conv)
    approve_tool_for_task(conv, "a")
    snap = approved_tools_for_task(conv)
    snap.add("b")  # mutating the snapshot must not affect the store
    assert is_tool_approved_for_task(conv, "b") is False
    clear_task_approvals(conv)


# ── tool_node wiring (source-grep, mirrors test_hitl_allow_always) ────────────


def test_tool_node_checks_task_approval_before_prompt() -> None:
    src = (_BACKEND / "app" / "services" / "tool_gateway.py").read_text(encoding="utf-8")
    # The check must run and be keyed by tool_name (args-agnostic), and gate
    # `needs_hitl` BEFORE request_validation is called.
    assert "is_tool_approved_for_task(_conv_id, tool_name)" in src, (
        "tool_node must check the task-scoped approval (by tool_name) before prompting"
    )
    # The handler for the new decision must register the approval.
    assert 'decision == "allow_for_task"' in src
    assert "approve_tool_for_task(_conv_id, tool_name)" in src


def test_validation_route_allow_for_task_exists() -> None:
    src = (_BACKEND / "app" / "routers" / "validation.py").read_text(encoding="utf-8")
    assert '"/{action_id}/allow_for_task"' in src, (
        "REST route /validation/{action_id}/allow_for_task must exist"
    )
    assert 'action_id, "allow_for_task"' in src


# ── frontend wiring (source-grep, mirrors test_hitl_allow_always) ─────────────


def test_api_client_accepts_allow_for_task_in_decision_type() -> None:
    src = (_FRONTEND / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert '"allow_for_task"' in src


def test_avatar_panel_has_allow_for_task_button() -> None:
    src = (_FRONTEND / "src" / "components" / "avatar" / "AvatarPanel.tsx").read_text(encoding="utf-8")
    assert 'resolveHitl("allow_for_task")' in src
    assert "hitlAllowForTask" in src


def test_hitl_bell_has_allow_for_task_button() -> None:
    src = (_FRONTEND / "src" / "components" / "layout" / "HitlBell.tsx").read_text(encoding="utf-8")
    assert '"allow_for_task"' in src
    assert "Pour cette tâche" in src


def test_i18n_messages_have_allow_for_task_key() -> None:
    fr = (_FRONTEND / "messages" / "fr.json").read_text(encoding="utf-8")
    en = (_FRONTEND / "messages" / "en.json").read_text(encoding="utf-8")
    assert "hitlAllowForTask" in fr and "Pour cette tâche" in fr
    assert "hitlAllowForTask" in en and "For this task" in en
