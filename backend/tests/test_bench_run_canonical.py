# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_bench_run_canonical.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — pin the bench harness contract :
#             discovery works, _render_summary is well-formed, scenarios
#             expose the right shape (NAME + DESCRIPTION + async run).
# @license    Elastic License 2.0
# =============================================================================
"""Tests for `bench/run_canonical.py` and the canonical scenarios.

These tests do NOT execute the scenarios in full (some need a fresh
SQLite + Qdrant) — that's the runner's job, invoked manually or by a
nightly cron. The pytest layer only verifies the harness structure :

  - Every scenario module follows the expected shape
  - The runner's discovery finds every scenario
  - The summary renderer produces valid markdown for both pass + fail
    inputs
  - The runner exits 0 on all-pass, 1 on any-fail
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def _make_bench_importable():
    """Ensure `import bench...` works for the tests below."""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    yield


# ── Scenario shape ────────────────────────────────────────────────────


_EXPECTED_SCENARIO_FILES = [
    "scenario_d_hitl_refusal_persisted",
    "scenario_e_hallucination_block_persisted",
    "scenario_f_memory_recall_returns_facts",
    "scenario_g_provider_switch_persisted",
    "scenario_h_prompt_version_chain",
]


@pytest.mark.parametrize("scenario_name", _EXPECTED_SCENARIO_FILES)
def test_each_canonical_scenario_exposes_expected_shape(scenario_name) -> None:
    import asyncio
    mod = importlib.import_module(f"bench.scenarios.canonical.{scenario_name}")
    assert hasattr(mod, "NAME"), f"{scenario_name} must declare NAME"
    assert hasattr(mod, "DESCRIPTION"), f"{scenario_name} must declare DESCRIPTION"
    assert hasattr(mod, "run"), f"{scenario_name} must declare async def run()"
    assert asyncio.iscoroutinefunction(mod.run), (
        f"{scenario_name}.run must be `async def`"
    )


# ── Runner discovery ─────────────────────────────────────────────────


def test_runner_discovers_all_scenarios() -> None:
    from bench.run_canonical import _discover
    found = _discover()
    for expected in _EXPECTED_SCENARIO_FILES:
        assert expected in found, (
            f"_discover() failed to find {expected}. Found: {found}"
        )


# ── Summary renderer ─────────────────────────────────────────────────


def test_render_summary_all_pass_shows_green() -> None:
    from bench.run_canonical import _render_summary
    md = _render_summary([
        {
            "scenario": "scenario_x",
            "name": "X — example pass",
            "description": "Sample.",
            "status": "pass",
            "duration_ms": 42,
            "result": {"pass": True, "checks": {"a": True, "b": True}},
        },
    ])
    assert "✅" in md
    assert "1/1 passed" in md
    assert "X — example pass" in md
    assert "scenario_x" in md
    assert "Failed : 0" in md


def test_render_summary_with_failure_shows_red_and_error() -> None:
    from bench.run_canonical import _render_summary
    md = _render_summary([
        {
            "scenario": "scenario_y",
            "name": "Y — example fail",
            "description": "Sample fail.",
            "status": "fail",
            "duration_ms": 10,
            "result": {
                "pass": False,
                "reason": "some reason",
                "failed_checks": ["check_a", "check_b"],
            },
            "error": "some reason",
        },
    ])
    assert "❌" in md
    assert "0/1 passed" in md
    assert "Failed : 1" in md
    assert "some reason" in md
    assert "check_a" in md and "check_b" in md


def test_render_summary_handles_import_error() -> None:
    """When a scenario fails to import (syntax error, missing deps), the
    runner must still produce a readable summary line."""
    from bench.run_canonical import _render_summary
    md = _render_summary([
        {
            "scenario": "scenario_broken",
            "name": "scenario_broken",
            "status": "import_error",
            "duration_ms": 5,
            "error": "ModuleNotFoundError: foo",
        },
    ])
    assert "❌" in md
    assert "ModuleNotFoundError" in md


# ── Runner exit code logic ────────────────────────────────────────────


def test_runner_returns_zero_on_all_pass(monkeypatch) -> None:
    """Stub `_discover` + `_run_one` so we exercise the exit-code logic
    without touching real DB."""
    import asyncio

    from bench import run_canonical

    monkeypatch.setattr(run_canonical, "_discover", lambda: ["scenario_x"])

    async def fake_run_one(name):
        return {
            "scenario": name,
            "name": name,
            "status": "pass",
            "duration_ms": 1,
            "result": {"pass": True, "checks": {"ok": True}},
        }

    monkeypatch.setattr(run_canonical, "_run_one", fake_run_one)
    rc = asyncio.run(run_canonical.main([]))
    assert rc == 0


def test_runner_returns_nonzero_on_any_fail(monkeypatch) -> None:
    import asyncio

    from bench import run_canonical

    monkeypatch.setattr(run_canonical, "_discover", lambda: ["scenario_x"])

    async def fake_run_one(name):
        return {
            "scenario": name,
            "name": name,
            "status": "fail",
            "duration_ms": 1,
            "result": {"pass": False, "reason": "intentional fail"},
            "error": "intentional fail",
        }

    monkeypatch.setattr(run_canonical, "_run_one", fake_run_one)
    rc = asyncio.run(run_canonical.main([]))
    assert rc == 1


def test_runner_returns_one_when_no_scenarios_discovered(monkeypatch) -> None:
    import asyncio

    from bench import run_canonical

    monkeypatch.setattr(run_canonical, "_discover", lambda: [])
    rc = asyncio.run(run_canonical.main([]))
    assert rc == 1
