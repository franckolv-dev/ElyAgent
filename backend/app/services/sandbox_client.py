# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/sandbox_client.py
# @brief      Sprint 4b V3 J2.d — backend client for the python_tool sandbox
#             runner (`POST /run`).
#
#             Provides a single coroutine, `run_in_sandbox(...)`, that POSTs
#             a job spec to the runner and returns a `SandboxResult`. Never
#             raises on a runner-side error — the outcome carries it. Only
#             raises on a programmer mistake (e.g. malformed source
#             argument).
#
#             Not yet wired into any execution path; the integration into
#             the agent flow lands in J6, gated by
#             `LEARNED_PYTHON_TOOLS_IO_ENABLED`. This module is shippable
#             standalone — its tests use mocked HTTP, no live sandbox.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Service URL — the sandbox is dual-homed (sandbox-net + cyberentity-net) so
# the backend resolves it by service name. Env override is useful for tests
# and for the future J6 dev loop.
DEFAULT_BASE_URL = os.environ.get("ELY_SANDBOX_URL", "http://sandbox:8080")

# Default wall-clock for a job. Matches the runner's own DEFAULT_TIMEOUT_S
# so neither side has to know about the other's cap.
DEFAULT_TIMEOUT_S = 8

# Hard ceiling on per-call timeout. Pure DoS guard — a misbehaving generator
# could otherwise pass `timeout_s=86400` and tie up a worker for a day.
MAX_TIMEOUT_S = 60

# Buffer added on top of the user-requested timeout for the HTTP-level wait.
# The runner has its own internal cap; this just keeps the network layer
# from giving up before the runner has finished serializing its response.
HTTP_OVERHEAD_S = 5


@dataclass(frozen=True)
class SandboxResult:
    """Mirrors the runner's RunResponse, plus an extra ``unavailable`` outcome
    for the case where the sandbox is unreachable at all (service down,
    network split). Same vocab as ``SmokeReport`` so callers can plug into
    the existing validation-pipeline handling.
    """

    # returned | raised | nonserializable | timeout | crashed | error | unavailable
    outcome: str
    duration_s: float = 0.0
    # Present when outcome=returned — the JSON-encoded result.
    result_json: str | None = None
    # Present when outcome=nonserializable — the result's repr().
    result_repr: str | None = None
    # Present when outcome=raised.
    error: str | None = None
    trace: str | None = None
    stage: str | None = None  # "import" or "call"
    # Present when outcome=timeout / crashed / error / unavailable.
    detail: str | None = None
    # Captured streams, size-capped by the runner.
    stdout: str = ""
    stderr: str = ""

    @property
    def is_ok(self) -> bool:
        """True iff the user code returned a JSON-serialisable value."""
        return self.outcome == "returned"

    @property
    def is_unavailable(self) -> bool:
        """True iff the sandbox itself couldn't be reached."""
        return self.outcome == "unavailable"


async def run_in_sandbox(
    source: str,
    func_name: str,
    *,
    kwargs: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    base_url: str = DEFAULT_BASE_URL,
) -> SandboxResult:
    """Submit a job spec to the sandbox runner. Returns the structured
    outcome — **never raises** on a runner-side problem.

    Args:
        source: The full module source of the python_tool. Already guarded
            and smoke'd upstream (J2-J6 pipeline); this function does NOT
            re-validate.
        func_name: Name of the callable to invoke after `exec`'ing `source`.
        kwargs: Keyword args passed to the callable (must be JSON-serialisable).
        secrets: Optional per-call secrets bag (V3 J6.b.1). Labels must
            match ``[a-z][a-z0-9_]{2,63}`` and values must be strings; the
            runner enforces the same shape with HTTP 422 on violation, so
            any malformed bag fails closed instead of slipping through.
            Available to the tool source as ``_SECRETS[label]`` /
            ``get_secret(label)``. Default ``None`` (treated as empty dict).
        timeout_s: Wall-clock cap. Clamped to [1, MAX_TIMEOUT_S].
        base_url: Override for the runner URL. Useful in tests.

    Raises:
        TypeError: only on a programmer error (`source` or `func_name` empty
            or wrong type).
    """
    if not isinstance(source, str) or not source.strip():
        raise TypeError("source must be a non-empty string")
    if not isinstance(func_name, str) or not func_name.strip():
        raise TypeError("func_name must be a non-empty string")

    timeout_s = max(1, min(int(timeout_s), MAX_TIMEOUT_S))
    payload = {
        "source": source,
        "func_name": func_name,
        "kwargs": kwargs or {},
        "secrets": secrets or {},
        "timeout_s": timeout_s,
    }
    http_timeout = timeout_s + HTTP_OVERHEAD_S

    try:
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            r = await client.post(f"{base_url}/run", json=payload)
    except httpx.ConnectError as exc:
        logger.warning("sandbox unreachable at %s: %s", base_url, exc)
        return SandboxResult(
            outcome="unavailable",
            detail=f"connect failed: {exc}",
        )
    except httpx.TimeoutException as exc:
        # The runner has its own wall-clock; this catches a hang in the
        # network/HTTP layer (e.g. proxy stall, container OOM-killed mid-
        # response). Surface as timeout so callers can retry-or-give-up
        # without distinguishing.
        logger.warning("sandbox HTTP timeout (%ss): %s", http_timeout, exc)
        return SandboxResult(
            outcome="timeout",
            detail=f"HTTP timeout after {http_timeout}s",
        )

    if r.status_code != 200:
        return SandboxResult(
            outcome="error",
            detail=f"sandbox HTTP {r.status_code}: {r.text[:200]}",
        )

    try:
        data = r.json()
    except ValueError as exc:
        return SandboxResult(
            outcome="error",
            detail=f"sandbox returned non-JSON: {exc}",
        )
    if not isinstance(data, dict):
        return SandboxResult(
            outcome="error",
            detail=f"sandbox returned non-object JSON: {type(data).__name__}",
        )

    return SandboxResult(
        outcome=str(data.get("outcome") or "error"),
        duration_s=float(data.get("duration_s") or 0.0),
        result_json=data.get("result_json"),
        result_repr=data.get("result_repr"),
        error=data.get("error"),
        trace=data.get("trace"),
        stage=data.get("stage"),
        detail=data.get("detail"),
        stdout=str(data.get("stdout") or ""),
        stderr=str(data.get("stderr") or ""),
    )
