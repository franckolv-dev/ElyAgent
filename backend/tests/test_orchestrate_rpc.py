# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_rpc.py
# @brief      Tests fonctionnels du RPC server UDS (Sprint 2.7 — Jalon 2).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Tests fonctionnels du RPC server UDS.

Couvre :
    1. ``start()`` crée le socket avec permissions 0o600.
    2. ``stop()`` cleanup le socket file.
    3. Round-trip request/response (dispatcher synchrone).
    4. Dispatcher asynchrone (coroutine awaited via event loop dédié).
    5. Dispatcher qui raise → error response, pas de crash thread.
    6. Tool hors allow-list → ToolNotAllowed.
    7. ``max_tool_calls`` dépassé → MaxToolCallsExceeded.
    8. ``tools_dispatched`` + ``dispatch_count`` s'incrémentent.
    9. Bad JSON / framing → ProtocolError + connexion fermée proprement.
   10. Double ``start()`` → RuntimeError.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
from pathlib import Path

import pytest

from app.services.orchestrate_rpc import (
    OrchestrateRPCServer,
    _HEADER_FMT,
    _HEADER_SIZE,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers (client-side framing, mirror image of _send/_recv_message)
# ──────────────────────────────────────────────────────────────────────


def _client_send(sock: socket.socket, data: dict) -> None:
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)


def _client_recv(sock: socket.socket) -> dict:
    header = _recv_n(sock, _HEADER_SIZE)
    (length,) = struct.unpack(_HEADER_FMT, header)
    payload = _recv_n(sock, length)
    return json.loads(payload.decode("utf-8"))


def _recv_n(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"peer closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def _connect(socket_path: Path) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(str(socket_path))
    return s


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


ALLOWED = frozenset({"gmail_list_emails", "drive_list_files", "web_search"})


@pytest.fixture
def echo_dispatcher():
    """Dispatcher synchrone qui retourne ``{tool, args}``."""
    def _dispatcher(tool: str, args: dict):
        return {"echoed_tool": tool, "echoed_args": args}
    return _dispatcher


@pytest.fixture
def started_server(echo_dispatcher):
    """RPC server started + cleanup at end of test."""
    server = OrchestrateRPCServer(
        user_id="test-user",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=echo_dispatcher,
    )
    socket_path = server.start()
    yield server, socket_path
    server.stop()


# ──────────────────────────────────────────────────────────────────────
# 1. start() / stop() / permissions
# ──────────────────────────────────────────────────────────────────────


def test_start_creates_socket_with_600_permissions(echo_dispatcher) -> None:
    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=echo_dispatcher,
    )
    try:
        socket_path = server.start()
        assert socket_path.exists()
        mode = os.stat(socket_path).st_mode & 0o777
        assert mode == 0o600, f"socket mode should be 0o600, got 0o{mode:o}"
    finally:
        server.stop()


def test_stop_removes_socket_file(echo_dispatcher) -> None:
    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=echo_dispatcher,
    )
    socket_path = server.start()
    assert socket_path.exists()
    server.stop()
    assert not socket_path.exists()


def test_double_start_raises(echo_dispatcher) -> None:
    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=echo_dispatcher,
    )
    try:
        server.start()
        with pytest.raises(RuntimeError, match="already started"):
            server.start()
    finally:
        server.stop()


# ──────────────────────────────────────────────────────────────────────
# 2. Round-trip avec dispatcher synchrone
# ──────────────────────────────────────────────────────────────────────


def test_roundtrip_sync_dispatcher(started_server) -> None:
    server, socket_path = started_server
    sock = _connect(socket_path)
    try:
        _client_send(sock, {"tool": "gmail_list_emails", "args": {"q": "x"}})
        response = _client_recv(sock)
    finally:
        sock.close()

    assert response["ok"] is True
    assert response["result"]["echoed_tool"] == "gmail_list_emails"
    assert response["result"]["echoed_args"] == {"q": "x"}
    assert server.dispatch_count == 1
    assert server.tools_dispatched == ["gmail_list_emails"]


def test_roundtrip_multiple_requests_same_connection(started_server) -> None:
    server, socket_path = started_server
    sock = _connect(socket_path)
    try:
        for tool in ["gmail_list_emails", "drive_list_files", "web_search"]:
            _client_send(sock, {"tool": tool, "args": {}})
            resp = _client_recv(sock)
            assert resp["ok"] is True
    finally:
        sock.close()

    assert server.dispatch_count == 3
    assert server.tools_dispatched == [
        "gmail_list_emails", "drive_list_files", "web_search",
    ]


# ──────────────────────────────────────────────────────────────────────
# 3. Dispatcher async (coroutine)
# ──────────────────────────────────────────────────────────────────────


def test_roundtrip_async_dispatcher() -> None:
    async def async_echo(tool: str, args: dict):
        await asyncio.sleep(0)  # actually be a coroutine
        return {"async_tool": tool, "args": args}

    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=async_echo,
    )
    try:
        socket_path = server.start()
        sock = _connect(socket_path)
        try:
            _client_send(sock, {"tool": "gmail_list_emails", "args": {"k": 1}})
            response = _client_recv(sock)
        finally:
            sock.close()
        assert response["ok"] is True
        assert response["result"] == {"async_tool": "gmail_list_emails", "args": {"k": 1}}
    finally:
        server.stop()


# ──────────────────────────────────────────────────────────────────────
# 4. Dispatcher qui raise — error response, pas de crash
# ──────────────────────────────────────────────────────────────────────


def test_dispatcher_exception_returns_error_response() -> None:
    def faulty(tool: str, args: dict):
        raise RuntimeError("boom")

    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=10,
        tool_dispatcher=faulty,
    )
    try:
        socket_path = server.start()
        sock = _connect(socket_path)
        try:
            _client_send(sock, {"tool": "gmail_list_emails", "args": {}})
            response = _client_recv(sock)
        finally:
            sock.close()
        assert response["ok"] is False
        assert response["error"] == "boom"
        assert response["error_type"] == "RuntimeError"
        # Counter should NOT increment on failure.
        assert server.dispatch_count == 0
        assert server.tools_dispatched == []
    finally:
        server.stop()


# ──────────────────────────────────────────────────────────────────────
# 5. Allow-list enforcement
# ──────────────────────────────────────────────────────────────────────


def test_tool_not_in_allow_list_is_refused(started_server) -> None:
    server, socket_path = started_server
    sock = _connect(socket_path)
    try:
        _client_send(sock, {"tool": "gmail_send_email", "args": {}})
        response = _client_recv(sock)
    finally:
        sock.close()

    assert response["ok"] is False
    assert response["error_type"] == "ToolNotAllowed"
    assert "gmail_send_email" in response["error"]
    assert server.dispatch_count == 0  # blocked before count


# ──────────────────────────────────────────────────────────────────────
# 6. max_tool_calls enforcement
# ──────────────────────────────────────────────────────────────────────


def test_max_tool_calls_blocks_further_dispatches(echo_dispatcher) -> None:
    server = OrchestrateRPCServer(
        user_id="u",
        allowed_tools=ALLOWED,
        max_tool_calls=2,  # tight cap for test
        tool_dispatcher=echo_dispatcher,
    )
    try:
        socket_path = server.start()
        sock = _connect(socket_path)
        try:
            # First two go through
            for _ in range(2):
                _client_send(sock, {"tool": "gmail_list_emails", "args": {}})
                resp = _client_recv(sock)
                assert resp["ok"] is True
            # Third must be refused
            _client_send(sock, {"tool": "gmail_list_emails", "args": {}})
            resp3 = _client_recv(sock)
            assert resp3["ok"] is False
            assert resp3["error_type"] == "MaxToolCallsExceeded"
        finally:
            sock.close()
        assert server.dispatch_count == 2
    finally:
        server.stop()


# ──────────────────────────────────────────────────────────────────────
# 7. Bad framing / bad JSON
# ──────────────────────────────────────────────────────────────────────


def test_bad_request_field_returns_bad_request_error(started_server) -> None:
    server, socket_path = started_server
    sock = _connect(socket_path)
    try:
        # Send a valid frame with an invalid request body.
        _client_send(sock, {"tool": "", "args": {}})
        response = _client_recv(sock)
    finally:
        sock.close()
    assert response["ok"] is False
    assert response["error_type"] == "BadRequest"


def test_invalid_json_payload_closes_connection_cleanly(started_server) -> None:
    _, socket_path = started_server
    sock = _connect(socket_path)
    try:
        # Send a header announcing 4 bytes, then "{xx}" (invalid JSON).
        bad_payload = b"{xx}"
        sock.sendall(struct.pack(_HEADER_FMT, len(bad_payload)) + bad_payload)
        response = _client_recv(sock)
    finally:
        sock.close()
    assert response["ok"] is False
    assert response["error_type"] == "ProtocolError"
