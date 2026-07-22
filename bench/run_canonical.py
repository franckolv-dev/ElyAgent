#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/run_canonical.py
# @brief      Sprint 3.7 V1.5 J7 + Sprint 3.7.3 J1 — canonical bench runner.
#             Discovers async scenarios in `bench/scenarios/canonical/`,
#             filters by --tag (shallow / medium / deep), executes them,
#             writes JSON + Markdown summary to `bench/results/<ts>/`.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Run the canonical scenarios + emit a results artefact.

Usage (from the project root) ::

    # Run every shallow scenario (CI nocturne default)
    cd backend && uv run python -m bench.run_canonical --tag shallow

    # Run shallow + medium together
    cd backend && uv run python -m bench.run_canonical --tag shallow,medium

    # Run absolutely everything (incl. real LLM calls — costs money)
    cd backend && uv run python -m bench.run_canonical --tag all

    # List scenarios + their tags without running anything
    cd backend && uv run python -m bench.run_canonical --list

Default when ``--tag`` is omitted : ``all`` (back-compat with the v1.5.0
behaviour, before the tag taxonomy existed).

Exit code :
  ``0`` if every selected scenario passed, ``1`` otherwise. Suitable for CI.

Discovery contract — see ``bench/scenarios/_base.py`` :
  - module name : ``scenario_*.py`` under ``bench/scenarios/canonical/``
  - exposes : ``NAME``, ``DESCRIPTION``, optional ``TAGS``, ``async def run() -> dict``
  - ``run()`` returns ``{"pass": bool, "checks": {...}, ...}``

The runner is independent of pytest — scenarios touch the real DB /
real services. That's the integration layer pytest fixtures can't
realistically cover.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
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


def _scenario_tags(mod: Any) -> list[str]:
    """Read a scenario's ``TAGS`` attribute, normalised against the
    canonical taxonomy. Missing or empty → ``["shallow"]``."""
    from bench.scenarios._base import normalise_tags
    return normalise_tags(getattr(mod, "TAGS", None))


def _parse_tag_arg(raw: str | None) -> set[str] | None:
    """Convert ``--tag shallow,medium`` → ``{"shallow", "medium"}``.

    Special values :
      ``None``  (arg omitted)  → returns ``None`` meaning "run everything"
      ``"all"``                → returns ``None`` (same as omitted)
    """
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw == "all":
        return None
    return {t.strip() for t in raw.split(",") if t.strip()}


async def _run_case_replay(case_id: int, skill_id: str | None) -> int:
    """C4-4 — replay shadow A/B d'un failure_case (déclenchement humain).

    Charge le cas réel, rejoue le tour SANS puis AVEC le skill lié
    (passerelle en mode shadow — aucun outil réel), imprime le rapport.
    Exit 0 si le run s'est déroulé (quel que soit le verdict), 1 sinon.
    """
    from app.services.learning.replay_engine import run_ab

    print(f"▶ Replay shadow A/B — failure_case #{case_id}"
          + (f" (skill forcé : {skill_id})" if skill_id else ""))
    report = await run_ab(case_id, skill_id=skill_id)
    status = report.get("status")
    if status != "ok":
        print(f"✗ replay impossible : {status}"
              + (f" — {report.get('hint')}" if report.get("hint") else ""))
        return 1

    def _fmt(run: dict[str, Any]) -> str:
        text = (run.get("final_text") or "").strip().replace("\n", " ")
        if len(text) > 300:
            text = text[:297] + "…"
        misses = run.get("shadow_misses") or []
        miss_note = f"  [outils non enregistrés tentés : {', '.join(misses)}]" if misses else ""
        return f"    blocked={run.get('blocked')}  «{text}»{miss_note}"

    print(f"  famille : {report['family']}  |  skill : {report['skill_id']}")
    print("  A (sans skill) :")
    print(_fmt(report["before"]))
    print("  B (avec skill) :")
    print(_fmt(report["after"]))
    print(f"  VERDICT : {report['verdict'].upper()}")
    ev = report.get("skill_eval") or {}
    if ev.get("status") == "evaluated":
        print(f"  2ᵉ avis skill_eval : score={ev.get('score')} verdict={ev.get('verdict')}")
    print("  (rapport écrit dans LearnedSkill.validation_report_json.replay_ab)")
    return 0


async def _run_one(module_name: str) -> dict[str, Any]:
    full = f"bench.scenarios.canonical.{module_name}"
    started = time.monotonic()
    try:
        mod = importlib.import_module(full)
    except Exception as exc:
        return {
            "scenario": module_name,
            "name": module_name,
            "tags": ["shallow"],
            "status": "import_error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    tags = _scenario_tags(mod)

    if not hasattr(mod, "run") or not asyncio.iscoroutinefunction(mod.run):
        return {
            "scenario": module_name,
            "name": getattr(mod, "NAME", module_name),
            "tags": tags,
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
            "tags": tags,
            "status": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    return {
        "scenario": module_name,
        "name": getattr(mod, "NAME", module_name),
        "description": getattr(mod, "DESCRIPTION", ""),
        "tags": tags,
        "status": "pass" if result.get("pass") else "fail",
        "duration_ms": int((time.monotonic() - started) * 1000),
        "result": result,
    }


def _render_summary(
    results: list[dict], selected_tags: set[str] | None = None,
) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = total - passed
    badge = "✅" if failed == 0 else "❌"

    tag_label = ",".join(sorted(selected_tags)) if selected_tags else "all"

    lines: list[str] = [
        f"# {badge} Canonical bench — {passed}/{total} passed (tags: {tag_label})",
        "",
        f"- Total scenarios : {total}",
        f"- Passed : {passed}",
        f"- Failed : {failed}",
        f"- Tag selection : {tag_label}",
        f"- Generated : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Per-scenario detail",
        "",
    ]
    for r in results:
        status_icon = "✅" if r["status"] == "pass" else "❌"
        tag_chip = " ".join(f"`{t}`" for t in r.get("tags", []))
        lines.append(f"### {status_icon} {r['name']} (`{r['scenario']}`) — {tag_chip}")
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


def _print_list(scenarios: list[str]) -> None:
    """Print discovered scenarios + their tags to stdout, no run."""
    _ensure_backend_importable()
    rows: list[tuple[str, str, str]] = []
    for s in scenarios:
        full = f"bench.scenarios.canonical.{s}"
        try:
            mod = importlib.import_module(full)
            name = getattr(mod, "NAME", s)
            tags = ",".join(_scenario_tags(mod))
        except Exception as exc:
            name = s
            tags = f"!import_error {type(exc).__name__}"
        rows.append((s, name, tags))
    name_w = max(len(r[0]) for r in rows) if rows else 0
    print(f"Discovered {len(rows)} scenario(s) :\n")
    for s, name, tags in rows:
        print(f"  {s.ljust(name_w)}  [{tags}]  {name}")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.run_canonical",
        description="Run ELY canonical bench scenarios.",
    )
    parser.add_argument(
        "--tag", "-t",
        help="Comma-separated tag list: shallow, medium, deep, all. "
             "Default: all (everything).",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List discovered scenarios + their tags, then exit.",
    )
    parser.add_argument(
        "--case", "-c",
        type=int,
        default=None,
        metavar="FAILURE_CASE_ID",
        help="C4-4 — replay shadow A/B d'un failure_case réel : rejoue le "
             "tour sans puis avec le skill lié (aucun outil réel exécuté, "
             "les résultats enregistrés sont re-servis), imprime le rapport "
             "avant/après, puis sort. Ignore --tag.",
    )
    parser.add_argument(
        "--skill",
        default=None,
        metavar="SKILL_ID",
        help="Avec --case : force le LearnedSkill à tester (défaut : le "
             "learned_skill_id du failure_case).",
    )
    args = parser.parse_args(argv or [])

    _ensure_backend_importable()

    if args.case is not None:
        return await _run_case_replay(args.case, args.skill)

    scenarios = _discover()
    if not scenarios:
        print("No canonical scenarios found in bench/scenarios/canonical/")
        return 1

    if args.list:
        _print_list(scenarios)
        return 0

    selected = _parse_tag_arg(args.tag)
    tag_label = ",".join(sorted(selected)) if selected else "all"
    print(f"Discovered {len(scenarios)} canonical scenario(s) — filter: {tag_label}")
    print("Running …")

    results: list[dict] = []
    skipped: list[str] = []
    for s in scenarios:
        full = f"bench.scenarios.canonical.{s}"
        try:
            mod = importlib.import_module(full)
            tags = _scenario_tags(mod)
        except Exception:
            tags = ["shallow"]

        if selected is not None and not (set(tags) & selected):
            skipped.append(s)
            continue

        print(f"  ▶ {s} [{','.join(tags)}] …", end="", flush=True)
        r = await _run_one(s)
        results.append(r)
        suffix = "OK" if r["status"] == "pass" else r["status"].upper()
        print(f" {suffix} ({r['duration_ms']} ms)")

    if not results:
        print(f"\nNo scenarios matched tag filter '{tag_label}' "
              f"({len(skipped)} skipped). Try --list to see available tags.")
        return 1

    # Persist
    ts = time.strftime("%Y-%m-%d-%H-%M")
    out_dir = _RESULTS_DIR / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(
            {
                "selected_tags": sorted(selected) if selected else ["all"],
                "skipped_count": len(skipped),
                "results": results,
            },
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    summary = _render_summary(results, selected)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")

    print()
    print(summary.splitlines()[0])  # title line
    if skipped:
        print(f"(skipped {len(skipped)} scenario(s) outside the tag filter)")
    print(f"Results → {out_dir.relative_to(_REPO_ROOT)}/")

    return 0 if all(r["status"] == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
