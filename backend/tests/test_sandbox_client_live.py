# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sandbox_client_live.py
# @brief      Sprint 4b V3 J2.d — OPTIONAL live integration test against a
#             running sandbox runner.
# @license    MIT
# =============================================================================
"""End-to-end test of the client against a real sandbox runner.

SKIPPED by default. Enable by:
  1. Bringing up the runner: `docker compose up -d sandbox`
  2. Setting ELY_SANDBOX_URL or accepting the default
     (http://localhost:8080 once you map the port locally).

CI doesn't run this — the runner E2E lives in `sandbox/test-sandbox-run.sh`
(invoked from the `sandbox-run` workflow job). This file is here so a dev
can validate the full chain backend→sandbox→subprocess in one command.
"""
from __future__ import annotations

import os

import httpx
import pytest

from app.services.sandbox_client import run_in_sandbox


LIVE_URL = os.environ.get("ELY_SANDBOX_URL_LIVE", "")


def _live_url_or_skip() -> str:
    if not LIVE_URL:
        pytest.skip("ELY_SANDBOX_URL_LIVE not set — live integration off by default")
    try:
        # Quick pre-flight so we fail fast with a clear message instead of
        # hanging inside the async client.
        with httpx.Client(timeout=2) as c:
            r = c.get(f"{LIVE_URL}/healthz")
            r.raise_for_status()
    except (httpx.HTTPError, httpx.RequestError) as exc:
        pytest.skip(f"sandbox runner not reachable at {LIVE_URL}: {exc}")
    return LIVE_URL


@pytest.mark.asyncio
async def test_live_pure_compute():
    url = _live_url_or_skip()
    result = await run_in_sandbox(
        "def double_it(x: int) -> int:\n    return x * 2\n",
        "double_it",
        kwargs={"x": 21},
        base_url=url,
    )
    assert result.is_ok, result
    assert result.result_json == "42"


@pytest.mark.asyncio
async def test_live_raise_is_captured():
    url = _live_url_or_skip()
    result = await run_in_sandbox(
        "def boom():\n    raise ValueError('intentional')\n",
        "boom",
        base_url=url,
    )
    assert result.outcome == "raised", result
    assert "ValueError" in (result.error or "")
