# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learned_tools_runtime_io.py
# @brief      Sprint 4b V3 J6.b.2 — runtime loader for io python_tool skills.
# @license    Elastic License 2.0
# =============================================================================
"""Pins the V3 runtime contract:

  1. The flag is OFF by default; ``load_active_io_tools`` returns [].
  2. The kill-switch (``LEARNED_PYTHON_TOOLS_DISABLED``) wins over the
     enabler (``LEARNED_PYTHON_TOOLS_IO_ENABLED``).
  3. A well-formed io skill yields a ``StructuredTool`` whose name +
     description + args_schema come from the AST — never from an exec.
  4. Invoking the tool resolves secrets via Vault then calls
     ``run_in_sandbox`` with the right payload (source / func_name /
     kwargs / secrets / timeout). Mocked end-to-end; no live sandbox.
  5. Failure modes degrade to clear LLM-visible strings, never raise:
     missing secret, vault locked, sandbox unreachable, raised in code,
     timeout, nonserializable, crashed.
  6. Skills with no @tool decorator are SKIPPED (logged), not raised.
"""
from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from app.services.learning import learned_tools_runtime_io as io_mod
from app.services.learning.learned_tools_runtime_io import (
    build_io_structured_tool,
    format_sandbox_result,
    io_tools_enabled,
    load_active_io_tools,
)
from app.services.sandbox_client import SandboxResult


# ── Source fixtures ─────────────────────────────────────────────────────────


_PROBE_SRC = textwrap.dedent("""
    from __future__ import annotations
    import httpx
    from langchain_core.tools import tool
    from app.skills.base import Domain
    from app.skills.decorator import register

    @register(
        domain=Domain.RESEARCH,
        skill_name="weather_probe",
        skill_display_name="Weather",
        skill_description="ping",
        skill_icon="i",
        enabled_by_default=False,
        network_allow=["api.openweathermap.org"],
        requires=["httpx"],
        requires_secrets=["openweather_api_key"],
    )
    @tool
    def weather_probe(city: str) -> int:
        \"\"\"Probe a city's weather and return the HTTP status code.\"\"\"
        api_key = get_secret("openweather_api_key")
        r = httpx.get(f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}", timeout=5)
        return r.status_code
""").strip()


_PURE_SRC_NO_SECRETS = textwrap.dedent("""
    from __future__ import annotations
    import httpx
    from langchain_core.tools import tool
    from app.skills.base import Domain
    from app.skills.decorator import register

    @register(
        domain=Domain.RESEARCH,
        skill_name="public_ping",
        skill_display_name="Ping",
        skill_description="x",
        skill_icon="i",
        enabled_by_default=False,
        network_allow=["example.com"],
        requires=["httpx"],
    )
    @tool
    def public_ping() -> int:
        \"\"\"Ping example.com and return its HTTP status.\"\"\"
        return httpx.get("https://example.com", timeout=5).status_code
""").strip()


_BAD_SRC = "def not_a_tool():\n    return 1\n"


# ── Fake vault ──────────────────────────────────────────────────────────────


class _FakeVault:
    def __init__(self, store: dict[str, str] | None = None):
        self._store = store or {}

    async def get_secret(self, user_id: str, label: str) -> str:  # noqa: ARG002
        if label not in self._store:
            raise KeyError(label)
        return self._store[label]


class _LockedVault:
    async def get_secret(self, user_id: str, label: str) -> str:  # noqa: ARG002
        raise PermissionError("vault is locked")


class _CrashingVault:
    async def get_secret(self, user_id: str, label: str) -> str:  # noqa: ARG002
        raise RuntimeError("postgres down")


# ── Flag behaviour ──────────────────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    """Deploying this module changes nothing — the flag must default OFF."""
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", raising=False)
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)
    assert io_tools_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_when_truthy(monkeypatch, val):
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", val)
    assert io_tools_enabled() is True


def test_kill_switch_beats_enabler(monkeypatch):
    """Master kill-switch contract — one env var disables ALL learned tools
    without redeploy. Same shape as the V2 module."""
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "1")
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_DISABLED", "1")
    assert io_tools_enabled() is False


# ── format_sandbox_result ───────────────────────────────────────────────────


def test_format_ok_returns_result_json_verbatim():
    r = SandboxResult(outcome="returned", result_json="42")
    assert format_sandbox_result(r) == "42"


def test_format_raised_includes_stage_and_error_truncated():
    r = SandboxResult(outcome="raised", stage="call", error="ValueError: x")
    s = format_sandbox_result(r)
    assert "[io tool call error]" in s
    assert "ValueError" in s


def test_format_timeout():
    r = SandboxResult(outcome="timeout", detail="wall-clock exceeded 8s")
    assert "[io tool timeout]" in format_sandbox_result(r)


def test_format_unavailable():
    r = SandboxResult(outcome="unavailable", detail="connect failed")
    assert "[io sandbox unreachable]" in format_sandbox_result(r)


def test_format_nonserializable():
    r = SandboxResult(outcome="nonserializable", result_repr="<object Foo>")
    s = format_sandbox_result(r)
    assert "JSON-serialisable" in s
    assert "Foo" in s


def test_format_crashed():
    r = SandboxResult(outcome="crashed", detail="wrapper exit code 137")
    assert "[io tool crashed]" in format_sandbox_result(r)


def test_format_unknown_outcome_falls_through():
    """A future runner introducing a new outcome value must not crash —
    we surface it textually so the LLM can see something is off."""
    r = SandboxResult(outcome="hypothetical_v3.x", detail="reason")
    s = format_sandbox_result(r)
    assert "hypothetical_v3.x" in s


# ── build_io_structured_tool — schema + dispatch ────────────────────────────


def test_build_returns_none_for_empty_source():
    assert build_io_structured_tool(source="", user_id="u") is None
    assert build_io_structured_tool(source="   \n", user_id="u") is None


def test_build_returns_none_for_source_without_tool_signature(caplog):
    """A function with no @tool decorator AND no docstring is not a learned
    tool — skip cleanly, log a warning."""
    with caplog.at_level("WARNING"):
        out = build_io_structured_tool(source=_BAD_SRC, user_id="u")
    assert out is None


def test_build_extracts_name_and_description_from_ast():
    tool = build_io_structured_tool(source=_PROBE_SRC, user_id="u1")
    assert tool is not None
    assert tool.name == "weather_probe"
    assert "weather" in tool.description.lower()
    # args_schema must have `city` field (the LLM-facing arg).
    schema = tool.args_schema.model_json_schema()
    assert "city" in schema["properties"]


def test_build_works_without_vault_when_no_secrets_declared():
    """A tool with no requires_secrets must build even when vault_service
    is None — the vault is only needed if the tool ASKS for secrets."""
    tool = build_io_structured_tool(
        source=_PURE_SRC_NO_SECRETS, user_id="u1", vault_service=None,
    )
    assert tool is not None
    assert tool.name == "public_ping"


# ── Dispatch (mocked run_in_sandbox + vault) ────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_happy_path_passes_secrets_to_sandbox():
    """The happy path — bind, await, see the right payload reach
    run_in_sandbox. This is the test that pins the wire contract: secrets
    must be resolved per call and forwarded as a dict by label."""
    vault = _FakeVault({"openweather_api_key": "sk-test"})
    captured: dict = {}

    async def _fake_run(source, func_name, *, kwargs, secrets, timeout_s, **rest):
        captured["source"] = source
        captured["func_name"] = func_name
        captured["kwargs"] = kwargs
        captured["secrets"] = secrets
        captured["timeout_s"] = timeout_s
        return SandboxResult(outcome="returned", result_json="200")

    with patch.object(io_mod, "run_in_sandbox", side_effect=_fake_run):
        tool = build_io_structured_tool(
            source=_PROBE_SRC, user_id="u1", vault_service=vault,
        )
        assert tool is not None
        result = await tool.ainvoke({"city": "Paris"})

    assert result == "200"
    assert captured["func_name"] == "weather_probe"
    assert captured["kwargs"] == {"city": "Paris"}
    assert captured["secrets"] == {"openweather_api_key": "sk-test"}


@pytest.mark.asyncio
async def test_dispatch_missing_secret_returns_clear_error_no_raise():
    """The user removed a Vault entry between bind and call — must not
    raise into the agent loop; surface a clear, LLM-readable string
    so the agent can ask the user to provision the secret."""
    vault = _FakeVault({})  # no entries

    with patch.object(io_mod, "run_in_sandbox") as fake_run:
        tool = build_io_structured_tool(
            source=_PROBE_SRC, user_id="u1", vault_service=vault,
        )
        result = await tool.ainvoke({"city": "Paris"})

    assert "openweather_api_key" in result
    assert "not provisioned" in result
    # And the sandbox was NEVER called.
    fake_run.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_locked_vault_returns_clear_error():
    vault = _LockedVault()
    with patch.object(io_mod, "run_in_sandbox") as fake_run:
        tool = build_io_structured_tool(
            source=_PROBE_SRC, user_id="u1", vault_service=vault,
        )
        result = await tool.ainvoke({"city": "Paris"})
    assert "locked" in result.lower()
    fake_run.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_no_vault_service_for_tool_that_needs_secrets():
    """Misconfiguration — a tool that declares secrets but the loader
    didn't inject a vault. Don't pretend it worked."""
    with patch.object(io_mod, "run_in_sandbox") as fake_run:
        tool = build_io_structured_tool(
            source=_PROBE_SRC, user_id="u1", vault_service=None,
        )
        result = await tool.ainvoke({"city": "Paris"})
    assert "config error" in result
    fake_run.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_skips_secrets_block_when_no_labels_declared():
    """A tool with no requires_secrets must not even consult the vault
    (saves a roundtrip and lets the no-secrets tools work with vault=None)."""
    async def _fake_run(*args, **kwargs):
        return SandboxResult(outcome="returned", result_json="200")

    with patch.object(io_mod, "run_in_sandbox", side_effect=_fake_run):
        tool = build_io_structured_tool(
            source=_PURE_SRC_NO_SECRETS, user_id="u1", vault_service=None,
        )
        result = await tool.ainvoke({})

    assert result == "200"


@pytest.mark.asyncio
async def test_dispatch_sandbox_raised_outcome():
    vault = _FakeVault({"openweather_api_key": "sk"})

    async def _fake_run(*args, **kwargs):
        return SandboxResult(
            outcome="raised", stage="call",
            error="ConnectError: timed out",
        )

    with patch.object(io_mod, "run_in_sandbox", side_effect=_fake_run):
        tool = build_io_structured_tool(
            source=_PROBE_SRC, user_id="u1", vault_service=vault,
        )
        result = await tool.ainvoke({"city": "Paris"})

    assert "[io tool call error]" in result
    assert "ConnectError" in result


# ── load_active_io_tools (DB-touching but flag-gated) ───────────────────────


@pytest.mark.asyncio
async def test_load_active_io_tools_empty_when_flag_off(monkeypatch):
    """Flag OFF → the loader is a no-op. Important: this must NOT touch
    the DB at all (no async_session). Pin by passing a clearly non-existent
    user_id; if the function tries to query, the test would still pass —
    so the real pin is the early return contract documented in the code.
    Here we just assert the [] result."""
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", raising=False)
    out = await load_active_io_tools("nonexistent_user")
    assert out == []
