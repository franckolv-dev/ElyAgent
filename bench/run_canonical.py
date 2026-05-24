#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/run_canonical.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical bench harness runner.
#             Discovers every async scenario module in
#             `bench/scenarios/canonical/`, executes them, writes a
#             JSON + Markdown summary to `bench/results/<timestamp>/`.
#
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Run the canonical scenarios + emit a results artefact.

Usage (from the project root) ::

    cd backend && uv run python -m bench.run_canonical

What gets run :
  Every module in ``bench/scenarios/canonical/`` whose name starts with
  ``scenario_`` and which exposes an async ``run()`` callable that
  returns a dict ``{"pass": bool, ...}``.

What gets written :
  ``bench/results/<YYYY-MM-DD-HH-MM>/``
    - ``results.json``  : raw structured data per scenario
    - ``summary.md``    : human-readable digest (pass/fail counts,
                          per-scenario detail, failed checks)

Exit code :
  ``0`` if every scenario passed, ``1`` otherwise. Suitable for CI.

This runner is **independent of pytest** — the scenarios touch the
real DB and real services, which is exactly what we want for a
"canonical missions" harness. The pytest suite covers the unit layer ;
this harness covers the integration layer that pytest fixtures can't
reach without setting up the full agent stack.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import pkgutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _REPO_ROOT / "backend"
_RESULTS_DIR = _REPO_ROOT / "bench" / "results"


def _ensure_backend_importable() -> None:
    """Allow `import app...` whether the user runs this from the project
    root, from `bench/`, or from `backend/`."""
    for p in (_BACKEND_ROOT, _REPO_ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _discover() -> list[str]:
    """Return canonical scenario module names (no package prefix)."""
    pkg_path = Path(__file__).parent / "scenarios" / "canonical"
    if not pkg_path.is_dir():
        return []
    names = []
    for entry in pkg_path.iterdir():
        if entry.is_file() and entry.name.startswith("scenario_") and entry.suffix == ".py":
            names.append(entry.stem)
    return sorted(names)


async def _run_one(module_name: str) -> dict[str, Any]:
    full = f"bench.scenarios.canonical.{module_name}"
    started = time.monotonic()
    try:
        mod = importlib.import_module(full)
    except Exception as exc:
        return {
            "scenario": module_name,
            "name": module_name,
            "status": "import_error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    if not hasattr(mod, "run") or not asyncio.iscoroutinefunction(mod.run):
        return {
            "scenario": module_name,
            "name": getattr(mod, "NAME", module_name),
            "status": "no_async_run",
            "error": "Module must expose `async def run() -> dict`.",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    try:
        result = await mod.run()
    except Exception as exc:
        return {
            "scenario": module_name,
            "name": getattr(mod, "NAME", module_name),
            "status": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    return {
        "scenario": module_name,
        "name": getattr(mod, "NAME", module_name),
        "description": getattr(mod, "DESCRIPTION", ""),
        "status": "pass" if result.get("pass") else "fail",
        "duration_ms": int((time.monotonic() - started) * 1000),
        "result": result,
    }


def _render_summary(results: list[dict]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = total - passed
    badge = "✅" if failed == 0 else "❌"

    lines: list[str] = [
        f"# {badge} Canonical bench — {passed}/{total} passed",
        "",
        f"- Total scenarios : {total}",
        f"- Passed : {passed}",
        f"- Failed : {failed}",
        f"- Generated : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Per-scenario detail",
        "",
    ]
    for r in results:
        status_icon = "✅" if r["status"] == "pass" else "❌"
        lines.append(f"### {status_icon} {r['name']} (`{r['scenario']}`)")
        lines.append("")
        if r.get("description"):
            lines.append(f"_{r['description']}_")
            lines.append("")
        lines.append(f"- Duration : {r['duration_ms']} ms")
        if r["status"] == "pass":
            checks = r.get("result", {}).get("checks") or {}
            if checks:
                lines.append(f"- Checks : {len(checks)}/{len(checks)} passed")
        else:
            err = r.get("error") or r.get("result", {}).get("reason") or "(no detail)"
            lines.append(f"- Error : `{err}`")
            failed_checks = r.get("result", {}).get("failed_checks") or []
            if failed_checks:
                lines.append(f"- Failed checks : {', '.join(failed_checks)}")
        lines.append("")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    _ensure_backend_importable()

    scenarios = _discover()
    if not scenarios:
        print("No canonical scenarios found in bench/scenarios/canonical/")
        return 1

    print(f"Discovered {len(scenarios)} canonical scenario(s) — running …")
    results: list[dict] = []
    for s in scenarios:
        print(f"  ▶ {s} …", end="", flush=True)
        r = await _run_one(s)
        results.append(r)
        suffix = "OK" if r["status"] == "pass" else r["status"].upper()
        print(f" {suffix} ({r['duration_ms']} ms)")

    # Persist
    ts = time.strftime("%Y-%m-%d-%H-%M")
    out_dir = _RESULTS_DIR / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    summary = _render_summary(results)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")

    print()
    print(summary.splitlines()[0])  # title line
    print(f"Results → {out_dir.relative_to(_REPO_ROOT)}/")

    return 0 if all(r["status"] == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
