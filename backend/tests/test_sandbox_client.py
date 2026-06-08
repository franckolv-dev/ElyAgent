# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sandbox_client.py
# @brief      Sprint 4b V3 J2.d — backend client for the python_tool sandbox.
# @license    Elastic License 2.0
# =============================================================================
"""Cover every outcome branch the runner can return, plus the network-level
failure modes (sandbox down, HTTP timeout, malformed response). All tests
use a mocked httpx — no live sandbox needed."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.sandbox_client import (
    DEFAULT_TIMEOUT_S,
    HTTP_OVERHEAD_S,
    MAX_TIMEOUT_S,
    SandboxResult,
    run_in_sandbox,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _patch_post(monkeypatch, *, json_data=None, text="", status_code=200,
                exc=None, capture: dict | None = None):
    """Patch httpx.AsyncClient.post. If ``capture`` is given, the (url, body)
    of each call is recorded there."""

    async def _fake_post(self, url, *, json=None, **_kwargs):  # noqa: ARG002
        if capture is not None:
            capture["url"] = url
            capture["json"] = json
        if exc is not None:
            raise exc
        request = httpx.Request("POST", url)
        if json_data is not None:
            return httpx.Response(status_code, request=request, json=json_data)
        return httpx.Response(status_code, request=request, text=text)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)


# ── happy path: returned ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returned_is_ok(monkeypatch):
    _patch_post(monkeypatch, json_data={
        "outcome": "returned", "duration_s": 0.04, "result_json": "42",
        "stdout": "hi", "stderr": "",
    })
    result = await run_in_sandbox("def f():\n    return 42\n", "f")
    assert result.is_ok is True
    assert result.outcome == "returned"
    assert result.result_json == "42"
    assert result.duration_s == 0.04
    assert result.stdout == "hi"


# ── outcome branches ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raised_preserves_error_and_trace(monkeypatch):
    _patch_post(monkeypatch, json_data={
        "outcome": "raised", "duration_s": 0.02, "stage": "call",
        "error": "ValueError: intentional",
        "trace": "Traceback (most recent call last):\n  …",
    })
    result = await run_in_sandbox("def boom():\n    raise ValueError\n", "boom")
    assert result.is_ok is False
    assert result.outcome == "raised"
    assert result.stage == "call"
    assert "ValueError" in (result.error or "")
    assert (result.trace or "").startswith("Traceback")


@pytest.mark.asyncio
async def test_runner_timeout_surfaces_as_timeout(monkeypatch):
    _patch_post(monkeypatch, json_data={
        "outcome": "timeout", "duration_s": 2.04,
        "detail": "wall-clock exceeded 2s",
    })
    result = await run_in_sandbox("def hang():\n    pass\n", "hang", timeout_s=2)
    assert result.outcome == "timeout"
    assert "2s" in (result.detail or "")
    assert result.is_ok is False


@pytest.mark.asyncio
async def test_nonserializable_surfaces_repr(monkeypatch):
    _patch_post(monkeypatch, json_data={
        "outcome": "nonserializable", "duration_s": 0.01,
        "result_repr": "<bytes len=4>",
    })
    result = await run_in_sandbox("def f():\n    return b'xxxx'\n", "f")
    assert result.outcome == "nonserializable"
    assert result.result_repr == "<bytes len=4>"


# ── network-level failures ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_error_is_unavailable(monkeypatch):
    _patch_post(monkeypatch, exc=httpx.ConnectError("no route"))
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "unavailable"
    assert result.is_unavailable is True
    assert "no route" in (result.detail or "")


@pytest.mark.asyncio
async def test_http_timeout_surfaces_as_timeout(monkeypatch):
    _patch_post(monkeypatch, exc=httpx.ReadTimeout("stalled"))
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "timeout"
    assert "HTTP timeout" in (result.detail or "")


@pytest.mark.asyncio
async def test_http_500_is_error(monkeypatch):
    _patch_post(monkeypatch, status_code=500, text="oops")
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "error"
    assert "500" in (result.detail or "")


@pytest.mark.asyncio
async def test_http_422_is_error(monkeypatch):
    _patch_post(monkeypatch, status_code=422, text="payload too large")
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "error"
    assert "422" in (result.detail or "")


@pytest.mark.asyncio
async def test_non_json_response_is_error(monkeypatch):
    _patch_post(monkeypatch, text="not-json")
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "error"
    assert "non-JSON" in (result.detail or "")


@pytest.mark.asyncio
async def test_non_object_json_is_error(monkeypatch):
    _patch_post(monkeypatch, json_data=["a", "list"])
    result = await run_in_sandbox("def f():\n    return 1\n", "f")
    assert result.outcome == "error"
    assert "non-object" in (result.detail or "")


# ── argument hygiene ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kwargs_are_forwarded(monkeypatch):
    capture: dict[str, Any] = {}
    _patch_post(monkeypatch, json_data={
        "outcome": "returned", "duration_s": 0, "result_json": "42",
    }, capture=capture)
    await run_in_sandbox("def f(x):\n    return x*2\n", "f", kwargs={"x": 21})
    assert capture["json"]["kwargs"] == {"x": 21}
    assert capture["json"]["source"].startswith("def f(x)")
    assert capture["json"]["func_name"] == "f"


@pytest.mark.asyncio
async def test_timeout_clamped_to_max(monkeypatch):
    """DoS guard: a caller (or a misbehaving generator) can't tie up a worker
    for hours with a giant timeout_s — we clamp before forwarding."""
    capture: dict[str, Any] = {}
    _patch_post(monkeypatch, json_data={
        "outcome": "returned", "duration_s": 0, "result_json": "1",
    }, capture=capture)
    await run_in_sandbox("def f():\n    return 1\n", "f", timeout_s=10_000)
    assert capture["json"]["timeout_s"] == MAX_TIMEOUT_S


@pytest.mark.asyncio
async def test_timeout_floored_to_one(monkeypatch):
    """Negative or zero timeout would let the runner fall back to its own
    default, masking the caller's bug — clamp to 1 instead."""
    capture: dict[str, Any] = {}
    _patch_post(monkeypatch, json_data={
        "outcome": "returned", "duration_s": 0, "result_json": "1",
    }, capture=capture)
    await run_in_sandbox("def f():\n    return 1\n", "f", timeout_s=0)
    assert capture["json"]["timeout_s"] == 1


@pytest.mark.asyncio
async def test_base_url_override_is_honoured(monkeypatch):
    capture: dict[str, Any] = {}
    _patch_post(monkeypatch, json_data={
        "outcome": "returned", "duration_s": 0, "result_json": "1",
    }, capture=capture)
    await run_in_sandbox(
        "def f():\n    return 1\n", "f",
        base_url="http://my-sandbox:9090",
    )
    assert capture["url"] == "http://my-sandbox:9090/run"


@pytest.mark.asyncio
async def test_empty_source_raises_typeerror():
    with pytest.raises(TypeError, match="source"):
        await run_in_sandbox("", "f")
    with pytest.raises(TypeError, match="source"):
        await run_in_sandbox("   \n", "f")


@pytest.mark.asyncio
async def test_empty_func_name_raises_typeerror():
    with pytest.raises(TypeError, match="func_name"):
        await run_in_sandbox("def f():\n    return 1\n", "")


# ── SandboxResult helpers ────────────────────────────────────────────────────


def test_sandbox_result_is_ok_only_for_returned():
    assert SandboxResult(outcome="returned", result_json="1").is_ok
    assert not SandboxResult(outcome="raised").is_ok
    assert not SandboxResult(outcome="timeout").is_ok
    assert not SandboxResult(outcome="unavailable").is_ok


def test_sandbox_result_is_unavailable():
    assert SandboxResult(outcome="unavailable").is_unavailable
    assert not SandboxResult(outcome="error").is_unavailable
    assert not SandboxResult(outcome="returned").is_unavailable


# ── pinning the timeout overhead constant ────────────────────────────────────


def test_overhead_is_at_least_one_second():
    """Keep the HTTP wait > the user wait so the network layer never gives
    up before the runner has finished serializing its response."""
    assert HTTP_OVERHEAD_S >= 1


def test_default_timeout_is_within_max():
    """The library default mustn't be silently clamped (would be a confusing
    surprise for callers)."""
    assert 1 <= DEFAULT_TIMEOUT_S <= MAX_TIMEOUT_S
