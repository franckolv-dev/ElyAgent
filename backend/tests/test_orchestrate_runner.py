# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_runner.py
# @brief      Tests fonctionnels du runner sandbox (Sprint 2.7 — Jalon 4).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests fonctionnels de ``OrchestrateRunner.run()``.

Couvre :
    1. Round-trip end-to-end avec un dispatcher mocké (sans toucher au
       registry réel — focus sur le pipeline runner/RPC/stubs/subprocess).
    2. Env scrubbing : tentative de smuggle d'une var ``XXX_SECRET_KEY`` →
       absente côté child.
    3. PYTHONPATH whitelist : le child ne peut pas importer ``app.``.
    4. HOME isolation : le child voit un HOME dans tmpdir, pas celui du
       parent.
    5. Timeout : un script qui dort 10s avec timeout 1s est tué, exit_code
       négatif, ``truncated=True``.
    6. Head+tail stdout truncation : un script qui spam 200 KB est capé
       au format head + ``[truncated N bytes]`` + tail.
    7. tools_dispatched est correctement remonté du RPC vers le result.
    8. tmpdir cleanup après le run (succès ou échec).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

from app.services.orchestrate_runner import (
    OrchestrateLimits,
    OrchestrateRunner,
    _build_scrubbed_env,
    _SAFE_ENV_PREFIXES,
    _SECRET_SUBSTRINGS,
)


# ──────────────────────────────────────────────────────────────────────
# Fixture — a minimal allow-list + mock dispatcher for full round-trips
# ──────────────────────────────────────────────────────────────────────


MOCK_ALLOWED = frozenset({"echo_tool", "double_tool"})


def _mock_dispatcher(tool_name: str, args: dict):
    """Synchronous dispatcher that returns deterministic data."""
    if tool_name == "echo_tool":
        return {"echoed": args}
    if tool_name == "double_tool":
        return {"result": int(args.get("n", 0)) * 2}
    raise LookupError(f"unknown mock tool {tool_name!r}")


@pytest.fixture
def fast_limits():
    """Limits tuned for fast tests — short timeout, small stdout cap."""
    return OrchestrateLimits(
        timeout_seconds=10,
        max_tool_calls=20,
        max_stdout_bytes=4_000,
        max_stderr_bytes=2_000,
        sigkill_grace_seconds=1.0,
    )


# A helper to generate stubs for the mock allow-list. ``generate_stubs``
# expects every tool name to exist in the real registry — for tests we
# need a different path. We monkey-patch the runner to skip stubs and
# write a hand-crafted ely_tools.py instead.
@pytest.fixture
def patched_stubs(monkeypatch, tmp_path):
    """Replace generate_stubs with a hand-written ely_tools.py.

    This keeps the test fully hermetic (no dependency on the live skill
    registry). The runner-side path is invariant to the stub
    generation strategy, so this faithfully exercises the production
    pipeline.
    """
    def _fake_generate(*, allowed_tools, socket_path, target_path):
        # Mirror the production preamble structure — just stub helpers
        # tailored to the mock tools.
        content = '''\
"""ely_tools (test-only) — minimal RPC stubs for the mock dispatcher."""
import json, os, socket, struct, threading
_SOCKET_PATH = os.environ["ELY_RPC_SOCKET"]
_HEADER_FMT = "!I"
_HEADER_SIZE = 4
_call_lock = threading.Lock()


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"truncated after {len(buf)}/{n}")
        buf.extend(chunk)
    return bytes(buf)


def _rpc(_tool, **kwargs):
    with _call_lock:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(_SOCKET_PATH)
            payload = json.dumps({"tool": _tool, "args": kwargs}, default=str).encode()
            s.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)
            header = _recv_exact(s, _HEADER_SIZE)
            (length,) = struct.unpack(_HEADER_FMT, header)
            resp = json.loads(_recv_exact(s, length).decode())
    if not resp.get("ok", False):
        raise RuntimeError(resp.get("error", "rpc error"))
    return resp.get("result")


def echo_tool(**kw):
    return _rpc("echo_tool", **kw)


def double_tool(n):
    return _rpc("double_tool", n=n)
'''
        target_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(
        "app.services.orchestrate_runner.generate_stubs", _fake_generate
    )


# ──────────────────────────────────────────────────────────────────────
# 1. End-to-end round-trip with the mock dispatcher
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_end_to_end_roundtrip(patched_stubs, fast_limits) -> None:
    code = """
from ely_tools import echo_tool, double_tool
r = echo_tool(hello="world")
n = double_tool(n=21)
print(f"echo={r['echoed']['hello']} double={n['result']}")
"""
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    assert result.exit_code == 0, (
        f"script exited {result.exit_code}, stderr={result.stderr!r}"
    )
    assert "echo=world double=42" in result.stdout
    assert result.tools_dispatched == ["echo_tool", "double_tool"]
    assert result.truncated is False


# ──────────────────────────────────────────────────────────────────────
# 2. Env scrubbing — secret substrings blocked
# ──────────────────────────────────────────────────────────────────────


def test_secret_substrings_in_env_are_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XXX_API_KEY", "should-not-leak")
    monkeypatch.setenv("MY_SECRET_THING", "definitely-not")
    monkeypatch.setenv("AUTH_HEADER", "bearer-...")
    # A non-secret var with a whitelisted prefix should pass through.
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    # An ELY_-prefixed var that doesn't look secret should pass too.
    monkeypatch.setenv("ELY_REGION", "eu-west-3")

    socket_path = tmp_path / "rpc.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    home.mkdir()

    env = _build_scrubbed_env(socket_path=socket_path, tmpdir=tmp_path, home_dir=home)

    assert "XXX_API_KEY" not in env
    assert "MY_SECRET_THING" not in env
    assert "AUTH_HEADER" not in env
    assert env.get("LANG") == "fr_FR.UTF-8"
    assert env.get("ELY_REGION") == "eu-west-3"
    # Mandatory overrides
    assert env["ELY_RPC_SOCKET"] == str(socket_path)
    assert env["HOME"] == str(home)
    assert env["PYTHONPATH"] == str(tmp_path)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_secret_substring_overrides_whitelisted_prefix(tmp_path, monkeypatch) -> None:
    """An ELY_-prefixed var that contains ``TOKEN`` must still be blocked."""
    monkeypatch.setenv("ELY_AUTH_TOKEN", "bearer-...")
    env = _build_scrubbed_env(
        socket_path=tmp_path / "rpc.sock",
        tmpdir=tmp_path,
        home_dir=tmp_path,
    )
    assert "ELY_AUTH_TOKEN" not in env


def test_pythonpath_does_not_inherit_backend(tmp_path, monkeypatch) -> None:
    """The child's PYTHONPATH must be exactly tmpdir — no backend path."""
    monkeypatch.setenv(
        "PYTHONPATH", "/opt/ely/backend:/usr/lib/python3.12/site-packages"
    )
    env = _build_scrubbed_env(
        socket_path=tmp_path / "rpc.sock",
        tmpdir=tmp_path,
        home_dir=tmp_path,
    )
    assert env["PYTHONPATH"] == str(tmp_path), (
        f"PYTHONPATH was {env['PYTHONPATH']!r}, expected {str(tmp_path)!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. PYTHONPATH isolation — child cannot import app.*
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_child_cannot_import_app_modules(patched_stubs, fast_limits) -> None:
    """A script that tries ``import app.services.vault_service`` must fail."""
    code = """
try:
    import app.services.vault_service  # noqa
    print("LEAK")
except ImportError:
    print("blocked")
except Exception as e:
    print(f"other:{type(e).__name__}")
"""
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    assert "blocked" in result.stdout
    assert "LEAK" not in result.stdout


# ──────────────────────────────────────────────────────────────────────
# 4. HOME isolation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_home_is_isolated_in_tmpdir(patched_stubs, fast_limits) -> None:
    code = """
import os
print(f"HOME={os.environ.get('HOME', 'unset')}")
"""
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    # The HOME printed must NOT be the test-runner's ~ — it should live
    # under a tmpdir we created.
    real_home = os.path.expanduser("~")
    assert f"HOME={real_home}" not in result.stdout
    assert "ely_orchestrate_" in result.stdout
    assert "/home" in result.stdout


# ──────────────────────────────────────────────────────────────────────
# 5. Timeout — script is killed, truncated=True
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_kills_long_running_script(patched_stubs) -> None:
    code = """
import time
print("starting")
time.sleep(30)
print("should never print")
"""
    limits = OrchestrateLimits(
        timeout_seconds=1,
        max_tool_calls=20,
        max_stdout_bytes=4_000,
        max_stderr_bytes=2_000,
        sigkill_grace_seconds=1.0,
    )
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    assert result.truncated is True
    assert "timeout" in result.truncation_reason.lower()
    assert "should never print" not in result.stdout
    assert result.duration_seconds >= 1.0
    # The process should be dead (negative exit code from SIGTERM/SIGKILL)
    assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────
# 6. Head+tail stdout truncation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stdout_head_tail_truncation(patched_stubs) -> None:
    code = """
# Emit enough bytes to overflow max_stdout_bytes (1 KB cap here).
for i in range(500):
    print(f"line{i:04d}_xxxxxxxxxxxxxxxxxxxx")
print("FINAL_MARKER")
"""
    limits = OrchestrateLimits(
        timeout_seconds=5,
        max_tool_calls=20,
        max_stdout_bytes=1_000,  # tight: forces overflow
        max_stderr_bytes=2_000,
        sigkill_grace_seconds=1.0,
    )
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    assert result.exit_code == 0
    assert result.truncated is True
    assert "truncated" in result.truncation_reason.lower()
    # Head: the first lines must be visible
    assert "line0000_" in result.stdout
    # Tail: the FINAL_MARKER (last print) must survive
    assert "FINAL_MARKER" in result.stdout
    # The truncation marker is in the middle
    assert "[truncated" in result.stdout


# ──────────────────────────────────────────────────────────────────────
# 7. tools_dispatched populated and ordered
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_dispatched_records_in_order(patched_stubs, fast_limits) -> None:
    code = """
from ely_tools import echo_tool, double_tool
echo_tool(a=1)
double_tool(n=2)
echo_tool(b=3)
print("ok")
"""
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    result = await runner.run(code=code)
    assert result.tools_dispatched == ["echo_tool", "double_tool", "echo_tool"]
    assert runner.last_run_tools_dispatched() == [
        "echo_tool", "double_tool", "echo_tool",
    ]


# ──────────────────────────────────────────────────────────────────────
# 8. tmpdir cleanup
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tmpdir_is_cleaned_up_after_run(patched_stubs, fast_limits) -> None:
    """After ``run()`` returns, the tmpdir should not exist on disk."""
    code = "print('hello')"
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    # Snapshot tmpdirs before — keep only the ones we'll create
    tmp_root = Path(tempfile.gettempdir())
    before = {
        p for p in tmp_root.iterdir()
        if p.name.startswith("ely_orchestrate_")
    }
    await runner.run(code=code)
    after = {
        p for p in tmp_root.iterdir()
        if p.name.startswith("ely_orchestrate_")
    }
    # Any new tmpdir created during the run must have been cleaned up.
    leaked = after - before
    assert not leaked, f"Runner leaked tmpdirs: {sorted(leaked)}"


@pytest.mark.asyncio
async def test_tmpdir_cleaned_up_even_on_script_failure(patched_stubs, fast_limits) -> None:
    code = "raise RuntimeError('boom')"
    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=fast_limits,
        allowed_tools=MOCK_ALLOWED,
    )
    tmp_root = Path(tempfile.gettempdir())
    before = {p for p in tmp_root.iterdir() if p.name.startswith("ely_orchestrate_")}
    result = await runner.run(code=code)
    assert result.exit_code != 0
    after = {p for p in tmp_root.iterdir() if p.name.startswith("ely_orchestrate_")}
    assert not (after - before)
