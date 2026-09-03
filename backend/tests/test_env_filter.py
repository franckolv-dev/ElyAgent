# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_env_filter.py
# @brief      Tests for the shared env-var filter helper
# @license    MIT
# =============================================================================
"""Tests for ``env_filter.filter_safe_env`` (Sprint 4a J1.5c).

The helper is the single source of truth for what env vars cross into
spawned subprocesses (orchestrate sandbox AND MCP stdio servers). It
must:
  - drop anything containing a secret substring, even if its prefix is
    whitelisted (defense in depth);
  - keep anything whose prefix matches the whitelist;
  - drop everything else.

These tests run against an in-memory source dict — no monkeypatching of
the real ``os.environ`` so they're hermetic and parallelisable.
"""
from __future__ import annotations

import os

from app.services.env_filter import filter_safe_env


_PREFIXES = ("PATH", "HOME", "ELY_", "UV_")
_SECRETS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")


def test_keeps_whitelisted_prefix():
    out = filter_safe_env(
        safe_prefixes=_PREFIXES,
        secret_substrings=_SECRETS,
        source={"PATH": "/usr/bin", "HOME": "/root", "FOO": "bar"},
    )
    assert out == {"PATH": "/usr/bin", "HOME": "/root"}


def test_drops_non_whitelisted_prefix():
    out = filter_safe_env(
        safe_prefixes=_PREFIXES,
        secret_substrings=_SECRETS,
        source={"DEBUG": "1", "FOO_BAR": "baz"},
    )
    assert out == {}


def test_blocks_secret_substring_even_if_prefix_matches():
    """Defense in depth: a future ``ELY_BACKUP_KEY`` is blocked the
    moment it's defined, without touching the safe_prefixes list."""
    out = filter_safe_env(
        safe_prefixes=_PREFIXES,
        secret_substrings=_SECRETS,
        source={
            "ELY_DEBUG": "1",           # kept (ELY_ prefix, no secret substr)
            "ELY_API_KEY": "sk-abc",    # dropped (contains KEY)
            "ELY_AUTH_TOKEN": "x",      # dropped (contains AUTH and TOKEN)
            "HOME": "/root",             # kept
            "DB_PASSWORD": "x",          # dropped (contains PASSWORD even though prefix doesn't match)
        },
    )
    assert out == {"ELY_DEBUG": "1", "HOME": "/root"}


def test_case_insensitive_secret_match():
    """Secret detection is uppercase-based on the var name. Practically
    env var names are uppercase, but we still cover lowercase to lock
    in the contract."""
    out = filter_safe_env(
        safe_prefixes=("API_",),
        secret_substrings=("KEY",),
        source={"API_key": "x", "API_VERSION": "1"},
    )
    # API_key uppercased is API_KEY which contains KEY → dropped
    assert "API_key" not in out
    assert out == {"API_VERSION": "1"}


def test_defaults_to_os_environ(monkeypatch):
    """When ``source`` is omitted, the helper reads from ``os.environ``."""
    monkeypatch.setenv("ELY_TEST_MARKER_8f2b", "kept")
    monkeypatch.setenv("FOO_TEST_MARKER_8f2b", "dropped")
    monkeypatch.delenv("ELY_TEST_KEY_8f2b", raising=False)
    out = filter_safe_env(
        safe_prefixes=("ELY_",),
        secret_substrings=("KEY",),
    )
    assert out.get("ELY_TEST_MARKER_8f2b") == "kept"
    assert "FOO_TEST_MARKER_8f2b" not in out


def test_empty_source_returns_empty_dict():
    assert filter_safe_env(
        safe_prefixes=_PREFIXES,
        secret_substrings=_SECRETS,
        source={},
    ) == {}


def test_returns_fresh_dict_not_alias_of_source():
    """The helper must return a new dict — callers add overrides on top."""
    source = {"HOME": "/root"}
    out = filter_safe_env(
        safe_prefixes=_PREFIXES,
        secret_substrings=_SECRETS,
        source=source,
    )
    out["HOME"] = "/elsewhere"
    assert source["HOME"] == "/root"
