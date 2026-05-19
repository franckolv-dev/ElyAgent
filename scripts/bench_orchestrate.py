#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       scripts/bench_orchestrate.py
# @brief      Bench wrapper for the orchestrate sandbox (Sprint 2.7 — Jalon 7b).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Bench wrapper for the orchestrate sandbox.

Usage:
    cd backend
    uv run python ../scripts/bench_orchestrate.py ../bench/scenarios/scenario_a_dev_weekly_summary.py
    uv run python ../scripts/bench_orchestrate.py ../bench/scenarios/scenario_b_memory_audit.py --json

What it measures
----------------
Server-side metrics for ONE run of a sandbox scenario:
    - duration_seconds  : wall-clock from runner.run() entry to exit
    - exit_code         : subprocess exit code (0 = clean)
    - tools_dispatched  : ordered list of tools the script called via RPC
    - stdout_bytes      : raw output size (after head+tail truncation if any)
    - stdout_tokens     : token estimate (chars / 4)
    - stderr_bytes      : stderr size
    - truncated         : whether stdout overflowed
    - truncation_reason : free-text reason (timeout / size cap)

What it does NOT measure
------------------------
The full V1-vs-V2 comparison requires a real LLM in the loop (Mistral
Large 3 or DeepSeek v4-pro) to count input/output tokens consumed for
the same workflow with and without orchestrate. That part of the bench
is run manually via the ELY backend — see ``bench/README.md``.

Output formats
--------------
- Default: human-readable ASCII table on stdout
- ``--json``: machine-readable JSON dump (useful for piping into another
  tool, or saving the full result for later aggregation)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _est_tokens(s: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars for English/French mix.

    For an accurate count, use tiktoken with the right model encoding,
    but for a bench report this approximation is within ±20% which is
    plenty for ratio comparisons.
    """
    return max(1, len(s) // 4) if s else 0


async def _run_scenario(scenario_path: Path, user_id: str) -> dict:
    """Load a scenario file (a .py script using ely_tools) and run it
    through OrchestrateRunner. Returns a dict with the measured metrics."""
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    code = scenario_path.read_text(encoding="utf-8")

    # Lazy imports so the script can be run without the full venv being
    # active at parse time (it still needs to be active at run time).
    from app.services.orchestrate_runner import OrchestrateRunner

    runner = OrchestrateRunner(user_id=user_id)
    result = await runner.run(code=code)

    return {
        "scenario": scenario_path.name,
        "user_id": user_id,
        "duration_seconds": round(result.duration_seconds, 3),
        "exit_code": result.exit_code,
        "tools_dispatched": result.tools_dispatched,
        "tools_dispatched_count": len(result.tools_dispatched),
        "stdout_bytes": len(result.stdout.encode("utf-8")),
        "stdout_tokens": _est_tokens(result.stdout),
        "stderr_bytes": len(result.stderr.encode("utf-8")),
        "stderr_tokens": _est_tokens(result.stderr),
        "truncated": result.truncated,
        "truncation_reason": result.truncation_reason,
        # Keep stdout for the human report (first 500 chars).
        "stdout_preview": result.stdout[:500],
    }


def _print_human_report(metrics: dict) -> None:
    """ASCII table format for terminal viewing."""
    out = sys.stdout
    out.write("\n")
    out.write("=" * 70 + "\n")
    out.write(f"  Bench: orchestrate sandbox — {metrics['scenario']}\n")
    out.write("=" * 70 + "\n\n")

    out.write(f"  user_id              {metrics['user_id']}\n")
    out.write(f"  exit_code            {metrics['exit_code']}\n")
    out.write(f"  duration_seconds     {metrics['duration_seconds']}\n")
    out.write(f"  tools_dispatched     {metrics['tools_dispatched_count']} "
              f"({', '.join(metrics['tools_dispatched']) or '—'})\n")
    out.write(f"  stdout_bytes         {metrics['stdout_bytes']}\n")
    out.write(f"  stdout_tokens (~)    {metrics['stdout_tokens']}\n")
    out.write(f"  stderr_bytes         {metrics['stderr_bytes']}\n")
    out.write(f"  truncated            {metrics['truncated']}\n")
    if metrics["truncated"]:
        out.write(f"    reason             {metrics['truncation_reason']}\n")
    out.write("\n")
    out.write("  stdout preview (first 500 chars):\n")
    out.write("  " + "-" * 68 + "\n")
    for line in metrics["stdout_preview"].splitlines()[:20]:
        out.write(f"    {line}\n")
    if len(metrics["stdout_preview"]) >= 500:
        out.write("    [truncated for preview …]\n")
    out.write("  " + "-" * 68 + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bench wrapper for the orchestrate sandbox.",
    )
    parser.add_argument(
        "scenario",
        type=Path,
        help="Path to a Python scenario file (uses ely_tools functions).",
    )
    parser.add_argument(
        "--user-id",
        default="bench-runner",
        help="user_id passed to the runner (default: bench-runner).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of the ASCII table.",
    )
    args = parser.parse_args()

    try:
        metrics = asyncio.run(_run_scenario(args.scenario, args.user_id))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        json.dump(metrics, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_human_report(metrics)

    # Non-zero exit if the sandbox itself failed — useful for CI / shell
    # pipelines that want to fail on a broken scenario.
    return 0 if metrics["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
