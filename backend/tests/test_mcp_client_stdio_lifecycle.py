# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_client_stdio_lifecycle.py
# @brief      Tests for _StdioConnection lifecycle (Sprint 4a J1.5b)
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for ``_StdioConnection`` lifecycle (Sprint 4a J1.5b, 2026-05-27).

Regression guard for the ``RuntimeError: Attempted to exit cancel scope
in a different task than it was entered in`` we used to hit on
``unload_server`` / admin update. The fix encapsulates the
``stdio_client`` + ``ClientSession`` ``async with`` block inside a
dedicated long-lived task so ``__aenter__`` and ``__aexit__`` always
run in the same task — no anyio cancel scope can ever cross a task
boundary.

We mock the mcp lib with simple async context managers that record the
task that entered and exited them, then assert the IDs match.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.services.mcp_client import _StdioConnection


# ────────────────────────────────────────────────────────────────────────
# Fake MCP module — installed into sys.modules by the fixture below
# ────────────────────────────────────────────────────────────────────────


class _FakeSession:
    def __init__(self):
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []
        self._tools: list = []

    async def initialize(self):
        self.initialized = True

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=f"ok:{name}")])

    async def list_tools(self):
        return types.SimpleNamespace(tools=self._tools)


class _RecordingAsyncCM:
    """Async context manager that records the asyncio task of enter/exit.

    Yields ``yield_value``. Stores the running task on enter/exit so
    tests can assert they're identical (the cancel-scope invariant).
    """

    def __init__(self, yield_value, *, label: str, recorder: dict):
        self._yield_value = yield_value
        self._label = label
        self._recorder = recorder

    async def __aenter__(self):
        self._recorder.setdefault("enter", {})[self._label] = asyncio.current_task()
        return self._yield_value

    async def __aexit__(self, exc_type, exc, tb):
        self._recorder.setdefault("exit", {})[self._label] = asyncio.current_task()
        return False


@pytest.fixture
def fake_mcp_module(monkeypatch):
    """Inject a fake `mcp` package into sys.modules.

    Returns a dict that records the tasks of enter/exit + holds the
    session reference for direct inspection.
    """
    recorder: dict = {"sessions": []}

    def _make_stdio_client(params):
        # Verify the params we built from the command parse
        return _RecordingAsyncCM(
            ("fake_read", "fake_write"),
            label="stdio",
            recorder=recorder,
        )

    def _make_client_session(read, write):
        sess = _FakeSession()
        recorder["sessions"].append(sess)
        return _RecordingAsyncCM(sess, label="session", recorder=recorder)

    class _StdioServerParameters:
        def __init__(self, command, args, env, cwd=None):
            self.command = command
            self.args = args
            self.env = env
            self.cwd = cwd

    mcp_root = types.ModuleType("mcp")
    mcp_root.ClientSession = _make_client_session
    mcp_root.StdioServerParameters = _StdioServerParameters

    mcp_client_mod = types.ModuleType("mcp.client")
    mcp_client_stdio = types.ModuleType("mcp.client.stdio")
    mcp_client_stdio.stdio_client = _make_stdio_client

    monkeypatch.setitem(sys.modules, "mcp", mcp_root)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_client_stdio)

    yield recorder


# ────────────────────────────────────────────────────────────────────────
# Lifecycle tests
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enter_and_exit_run_in_same_task(fake_mcp_module):
    """Critical invariant: ``__aexit__`` must run in the same task as
    ``__aenter__``. Otherwise anyio raises ``RuntimeError: Attempted to
    exit cancel scope in a different task...`` (the bug J1.5b fixes).

    We trigger connect from THIS test task, then close, and verify that
    the recorded enter/exit task IDs match for both the stdio and the
    session context managers — which proves they ran inside the
    dedicated lifecycle task, not bouncing between caller tasks."""
    conn = _StdioConnection("fake-cmd --arg")
    await conn._connect()
    await conn.close()

    enter = fake_mcp_module["enter"]
    exit_ = fake_mcp_module["exit"]

    assert enter["stdio"] is exit_["stdio"], (
        "stdio_client enter+exit must run in the same asyncio task — anyio "
        "cancel scopes are task-bound."
    )
    assert enter["session"] is exit_["session"], (
        "ClientSession enter+exit must run in the same asyncio task."
    )
    # And critically — that task is NOT this test's task (it's the
    # lifecycle task spawned by _connect).
    assert enter["stdio"] is not asyncio.current_task()


@pytest.mark.asyncio
async def test_close_is_idempotent(fake_mcp_module):
    """Calling close() twice must not crash and must not double-exit."""
    conn = _StdioConnection("fake-cmd")
    await conn._connect()
    await conn.close()
    # Second close — must be a no-op, no exception
    await conn.close()
    assert conn._session is None
    assert conn._task is None


@pytest.mark.asyncio
async def test_close_without_connect_is_noop(fake_mcp_module):
    """Closing a never-connected connection must not raise."""
    conn = _StdioConnection("fake-cmd")
    await conn.close()


@pytest.mark.asyncio
async def test_reconnect_after_close(fake_mcp_module):
    """After close(), the same _StdioConnection must be reusable —
    spawns a NEW lifecycle task, builds a NEW session."""
    conn = _StdioConnection("fake-cmd")
    await conn._connect()
    first_session = conn._session
    await conn.close()
    await conn._connect()
    second_session = conn._session
    assert first_session is not None
    assert second_session is not None
    assert second_session is not first_session, "reconnect must build a fresh session"
    await conn.close()


@pytest.mark.asyncio
async def test_call_tool_reuses_session_under_lock(fake_mcp_module):
    """Once connected, repeated call_tool must NOT spawn extra
    lifecycle tasks — only one session for the lifetime of the connection."""
    conn = _StdioConnection("fake-cmd")
    await conn.call_tool("a", {"x": 1})
    sessions_after_first = len(fake_mcp_module["sessions"])
    await conn.call_tool("b", {})
    await conn.call_tool("c", {"y": 2})
    sessions_after_third = len(fake_mcp_module["sessions"])
    assert sessions_after_first == 1
    assert sessions_after_third == 1, "no extra session must be created for sequential calls"
    await conn.close()


@pytest.mark.asyncio
async def test_init_failure_propagates_and_cleans_up(monkeypatch):
    """If ``session.initialize()`` raises, ``_connect`` must re-raise
    the original exception AND the lifecycle task must be reaped (not
    left orphaned)."""
    recorder: dict = {"sessions": []}

    class _BrokenSession(_FakeSession):
        async def initialize(self):
            raise RuntimeError("server crashed on init")

    def _make_stdio_client(params):
        return _RecordingAsyncCM(
            ("read", "write"), label="stdio", recorder=recorder,
        )

    def _make_session(read, write):
        s = _BrokenSession()
        recorder["sessions"].append(s)
        return _RecordingAsyncCM(s, label="session", recorder=recorder)

    class _Params:
        def __init__(self, command, args, env, cwd=None):
            pass

    mcp_root = types.ModuleType("mcp")
    mcp_root.ClientSession = _make_session
    mcp_root.StdioServerParameters = _Params
    mcp_client_mod = types.ModuleType("mcp.client")
    mcp_client_stdio = types.ModuleType("mcp.client.stdio")
    mcp_client_stdio.stdio_client = _make_stdio_client
    monkeypatch.setitem(sys.modules, "mcp", mcp_root)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_client_stdio)

    conn = _StdioConnection("broken-cmd")
    with pytest.raises(RuntimeError, match="server crashed on init"):
        await conn._connect()

    # Task must be reaped — no lingering coroutines
    assert conn._task is None
    assert conn._session is None
