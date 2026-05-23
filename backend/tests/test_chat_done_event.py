# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_chat_done_event.py
# @brief      Hotfix 2026-05-23 — pin the `{"type": "done"}` turn-end event
#             contract added to chat.py so the frontend can reliably flip
#             `isLoading=false` and the user can answer ELY's questions.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Regression tests for the chat input lock bug (2026-05-23).

Symptom (production, ely.catalogmaker.fr, DeepSeek v4-pro tier C) :
  ELY ends a turn with a question to the user. The red square stop
  button stays visible. User types "oui" + Enter → nothing happens.
  User clicks the stop button → nothing happens. Only a page refresh
  unblocks. Whole conversation is lost.

Root cause :
  React batched the `setIsLoading(false)` triggered by the "message"
  event. The next keystroke caught the stale `isLoading=true` and
  `handleKeyDown` interpreted Enter as `onStop()`. Stop arrived at the
  backend after the agent loop had already exited — handled by the
  pre-loop guard at chat.py:163-164 which just `continue`s. Frontend
  never got an explicit "you're back to idle" signal → stayed locked.

Fix :
  Backend emits `{"type": "done"}` in 3 paths :
    1. After every "message" event (normal turn end).
    2. After every "stopped" event (interrupted turn).
    3. On receipt of "stop" while no agent is running (race recovery).

  Frontend handles "done" → `setIsLoading(false)` defensively.

  Frontend `handleKeyDown` no longer converts Enter to `onStop()` when
  `isLoading=true` — it's now a no-op (the user must explicitly click
  the red square to abort).

These tests grep the source to pin the contract. Full WebSocket
round-trip tests would need a fastapi test client + a fake graph, which
is out of scope for a regression hotfix.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]


# ── Backend chat.py emits "done" in the 3 expected paths ─────────────


def test_chat_router_emits_done_after_message_event() -> None:
    """The main happy path — after the assistant message payload is
    sent, an explicit `{"type": "done"}` must follow on the same WS."""
    src = (_REPO / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    # The order matters : "done" must appear AFTER the payload-send line.
    payload_send = 'await websocket.send_text(_dumps(payload))'
    done_send = '_dumps({"type": "done"})'
    assert payload_send in src
    assert done_send in src
    # There are multiple `done` sends now (one per code path). Verify the
    # payload-send is followed by a `done` send within the next 500 chars.
    payload_idx = src.index(payload_send)
    window = src[payload_idx:payload_idx + 500]
    assert done_send in window, (
        "The `done` event must be sent within ~500 chars after the assistant "
        "`message` event."
    )


def test_chat_router_emits_done_after_stopped_event() -> None:
    """Interrupt path — "stopped" + "done" pair so the frontend can
    flip isLoading=false regardless of which event it handles first."""
    src = (_REPO / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    stopped_send = '_dumps({"type": "stopped"})'
    done_send = '_dumps({"type": "done"})'
    assert stopped_send in src
    assert done_send in src
    # In the source, the "stopped" line should be followed (within ~5 lines)
    # by a "done" send. We grep the joined region for proximity.
    stopped_idx = src.index(stopped_send)
    # Look for "done" send within the next 500 chars after "stopped"
    window = src[stopped_idx:stopped_idx + 500]
    assert done_send in window, (
        "After sending `stopped`, the same code path must send `done` "
        "(within ~500 chars) so the frontend unlocks reliably."
    )


def test_chat_router_emits_done_on_stop_with_no_agent_running() -> None:
    """The race-recovery path : user clicks stop AFTER the agent
    finished. Backend acknowledges with `done` instead of silently
    ignoring the message."""
    src = (_REPO / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    stop_guard = 'if msg.get("type") == "stop":'
    done_send = '_dumps({"type": "done"})'
    assert stop_guard in src
    assert done_send in src
    # The first occurrence of the stop-guard must be quickly followed
    # by a "done" send (within ~400 chars).
    guard_idx = src.index(stop_guard)
    window = src[guard_idx:guard_idx + 400]
    assert done_send in window, (
        "The pre-loop stop guard must emit `done` so a stop clicked "
        "after the agent finished doesn't leave the frontend stuck."
    )


# ── Frontend handler is wired ─────────────────────────────────────────


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def test_frontend_chat_page_handles_done_event() -> None:
    src = (_FRONTEND / "src" / "app" / "chat" / "page.tsx").read_text(encoding="utf-8")
    assert 'msg.type === "done"' in src, (
        "frontend/src/app/chat/page.tsx must add a handler for "
        "the new `done` event."
    )
    # That handler must also setIsLoading(false) — the whole point of the fix
    done_idx = src.index('msg.type === "done"')
    # Window large enough to cover the (verbose) inline comment + the
    # actual setState calls.
    window = src[done_idx:done_idx + 1200]
    assert "setIsLoading(false)" in window


def test_frontend_keydown_no_longer_calls_onstop_on_enter_during_loading() -> None:
    """The handleKeyDown previously converted Enter→onStop when
    `isLoading=true`. That's exactly the path that caused the bug.
    Pin that the new code returns early instead."""
    src = (
        _FRONTEND / "src" / "components" / "chat" / "ChatInput.tsx"
    ).read_text(encoding="utf-8")
    # Grep the handleKeyDown function specifically
    kd_idx = src.index("handleKeyDown")
    # Take the next 600 chars — should encompass the whole callback body
    region = src[kd_idx:kd_idx + 1000]
    # The old behaviour was `if (isLoading) { onStop?.(); }`. Forbid that.
    assert "onStop?.()" not in region, (
        "handleKeyDown must NOT call onStop() — that's the bug we just fixed. "
        "Enter during loading should be a no-op now (user clicks the red "
        "square explicitly to abort)."
    )
    # The fixed code returns early instead — pin the marker
    assert "Hotfix 2026-05-23" in region


def test_frontend_wsmessage_type_includes_done() -> None:
    """The TypeScript discriminated union must accept the new event type
    so the page handler doesn't error at build time."""
    src = (_FRONTEND / "src" / "lib" / "types.ts").read_text(encoding="utf-8")
    assert '| "done"' in src, (
        "WSMessage type union in types.ts must include `done` for "
        "the new turn-end event."
    )
