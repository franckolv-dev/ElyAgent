# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_client_env_scrub.py
# @brief      Tests for _build_mcp_env (Sprint 4a J1.5c)
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for the MCP env scrubbing helper.

`MCPClientManager._build_tools` used to pass ``json.loads(srv.env_json)``
straight into ``StdioServerParameters``, which gave the spawned MCP
server **the full backend environment** — including
``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GITHUB_TOKEN``, DB
credentials, etc. — until the OS-level inheritance was bypassed by
explicitly passing ``env=``. The new ``_build_mcp_env`` runs the same
prefix-whitelist + secret-blocklist filter we use for the orchestrate
sandbox, then layers the admin-supplied JSON overrides on top.
"""
from __future__ import annotations

import os

from app.services.mcp_client import _build_mcp_env


def test_filters_out_secrets_from_os_environ(monkeypatch):
    """API keys / tokens in the backend env must NOT cross into the
    spawned MCP server."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_leak")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

    env = _build_mcp_env(None)

    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert env.get("PATH") == "/usr/local/bin:/usr/bin"


def test_keeps_uv_env_for_uv_tool_run(monkeypatch):
    """`uv tool run mcp-server-time` requires UV_TOOL_DIR / UV_CACHE_DIR
    to be inherited (J1.5d sets them in docker-compose.yml). The prefix
    list must include UV_."""
    monkeypatch.setenv("UV_TOOL_DIR", "/tmp/uv-tools")
    monkeypatch.setenv("UV_CACHE_DIR", "/tmp/uv-cache")

    env = _build_mcp_env(None)

    assert env.get("UV_TOOL_DIR") == "/tmp/uv-tools"
    assert env.get("UV_CACHE_DIR") == "/tmp/uv-cache"


def test_admin_env_json_overrides_layer_on_top(monkeypatch):
    """Admin-supplied env via the UI wins — even for a "secret-looking"
    key, because the admin explicitly typed it into the form."""
    monkeypatch.setenv("PATH", "/usr/bin")

    env_json = '{"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_admin_chose_this", "FOO": "bar"}'
    env = _build_mcp_env(env_json)

    # Admin override wins
    assert env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_admin_chose_this"
    assert env["FOO"] == "bar"
    # Filtered defaults still present
    assert env["PATH"] == "/usr/bin"


def test_no_env_json_means_no_overrides():
    """A None env_json must not crash and must not add anything."""
    env_a = _build_mcp_env(None)
    env_b = _build_mcp_env("")
    # Same set of inherited vars (modulo timing) — both must be dicts
    assert isinstance(env_a, dict)
    assert isinstance(env_b, dict)


def test_invalid_env_json_is_logged_and_ignored(monkeypatch, caplog):
    """A malformed env_json must not crash the MCP loader. The default
    scrubbed env still applies."""
    monkeypatch.setenv("PATH", "/usr/bin")
    env = _build_mcp_env("not-json{")
    assert env["PATH"] == "/usr/bin"
    # No GHTOKEN-style sneaky injection survived
    assert all(":" not in v or v == "/usr/bin" for v in env.values())


def test_non_string_values_in_env_json_are_dropped(monkeypatch):
    """MCP server env must be a {str: str} mapping. Numeric or list
    values in the admin JSON must be silently dropped, not coerced."""
    monkeypatch.setenv("PATH", "/usr/bin")
    env_json = '{"COUNT": 3, "LIST": ["a", "b"], "GOOD": "ok"}'
    env = _build_mcp_env(env_json)
    assert env.get("GOOD") == "ok"
    assert "COUNT" not in env
    assert "LIST" not in env


def test_env_json_not_a_dict_is_ignored(monkeypatch):
    """`env_json` like '"hello"' or '[1,2]' is well-formed JSON but not
    a dict — must be ignored, not crash."""
    monkeypatch.setenv("PATH", "/usr/bin")
    for bad in ('"just a string"', '[1, 2, 3]', '42', 'null'):
        env = _build_mcp_env(bad)
        assert env.get("PATH") == "/usr/bin"
