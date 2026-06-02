# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/static_checks.py
# @brief      Sprint 4b V2 J3 — ruff + mypy stages of the @tool validation
#             pipeline (stages 2 + 3, after code_guard's AST allow-list).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Static analysis of generated ``@tool`` source (design note J0 §3.3).

After ``code_guard`` (stage 1, security allow-list) passes, the source is
linted and type-checked:

  - **ruff** (stage 2) — pyflakes/pycodestyle. The high-value catch is
    F821 (undefined name): an LLM that references a tool or symbol that
    doesn't exist is caught here, cheaply, before the smoke sandbox.
  - **mypy** (stage 3) — type consistency of the function signature +
    body, so ``bind_tools`` gets a coherent args schema. Run lenient
    (``--ignore-missing-imports --follow-imports=skip``) because the
    generated code imports langchain/app modules that have no stubs in
    this checking context — we care about the *tool's own* types, not
    the whole import graph.

Both run **in-process at skill-generation time** (not just CI), so ruff
and mypy are declared as runtime deps (pyproject). The checks are
hermetic: ruff runs ``--isolated`` (ignores the project's ruff config)
so the verdict doesn't drift as the repo lint prefs evolve.

Fail-closed: if a checker can't be invoked at all, the report is
``available=False`` and ``ok=False`` — a missing checker must never let
a candidate through.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_STDIN_FILENAME = "generated_tool.py"
_TIMEOUT_S = 30


# ── Result types (mirror code_guard's shape) ─────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """One lint/type finding. ``tool`` is 'ruff' or 'mypy'; ``code`` is the
    rule id (F821, return-value, …) or '' when none."""

    tool: str
    code: str
    message: str
    lineno: int
    col: int

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        c = f" [{self.code}]" if self.code else ""
        return f"{self.tool}{c} line {self.lineno}: {self.message}"


@dataclass(frozen=True)
class StaticCheckReport:
    ok: bool
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    # False when the underlying tool could not be invoked → fail-closed.
    available: bool = True

    def summary(self) -> str:
        if not self.available:
            return "; ".join(str(f) for f in self.findings) or "checker unavailable"
        if self.ok:
            return "ok"
        return "; ".join(str(f) for f in self.findings)


# ── ruff (stage 2) ────────────────────────────────────────────────────────────


def _ruff_exe() -> str | None:
    """Resolve the ruff console script next to the running interpreter
    (the venv ruff installed as a runtime dep)."""
    cand = Path(sys.executable).parent / "ruff"
    if cand.exists():
        return str(cand)
    import shutil

    return shutil.which("ruff")


def run_ruff(source: str, *, select: tuple[str, ...] = ("E", "F")) -> StaticCheckReport:
    """Lint ``source`` with ruff, isolated from the project config."""
    exe = _ruff_exe()
    if exe is None:
        return StaticCheckReport(
            ok=False,
            available=False,
            findings=(Finding("ruff", "", "ruff executable not found", 0, 0),),
        )

    cmd = [
        exe,
        "check",
        "--isolated",
        "--select",
        ",".join(select),
        "--output-format",
        "json",
        "--stdin-filename",
        _STDIN_FILENAME,
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=source,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return StaticCheckReport(
            ok=False,
            available=False,
            findings=(Finding("ruff", "", f"ruff invocation failed: {exc}", 0, 0),),
        )

    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return StaticCheckReport(
            ok=False,
            available=False,
            findings=(
                Finding("ruff", "", f"ruff output not parseable: {proc.stderr[:200]}", 0, 0),
            ),
        )

    findings = tuple(
        Finding(
            tool="ruff",
            code=(it.get("code") or ""),
            message=it.get("message", ""),
            lineno=(it.get("location") or {}).get("row", 0),
            col=(it.get("location") or {}).get("column", 0),
        )
        for it in items
    )
    return StaticCheckReport(ok=not findings, findings=findings)


# ── mypy (stage 3) ─────────────────────────────────────────────────────────────


_MYPY_LINE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<sev>error|warning|note):\s+(?P<msg>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)


def run_mypy(source: str) -> StaticCheckReport:
    """Type-check ``source`` with mypy in lenient mode (we want the tool's
    own type consistency, not the whole import graph)."""
    try:
        from mypy import api as mypy_api
    except ImportError as exc:  # pragma: no cover - mypy is a declared dep
        return StaticCheckReport(
            ok=False,
            available=False,
            findings=(Finding("mypy", "", f"mypy not importable: {exc}", 0, 0),),
        )

    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / _STDIN_FILENAME
        src_path.write_text(source, encoding="utf-8")
        cache_dir = Path(tmp) / ".mypy_cache"

        args = [
            str(src_path),
            "--ignore-missing-imports",
            "--follow-imports=skip",
            "--show-column-numbers",
            "--no-error-summary",
            "--no-color-output",
            "--no-incremental",
            f"--cache-dir={cache_dir}",
        ]
        try:
            stdout, _stderr, _status = mypy_api.run(args)
        except Exception as exc:  # pragma: no cover - defensive
            return StaticCheckReport(
                ok=False,
                available=False,
                findings=(Finding("mypy", "", f"mypy run failed: {exc}", 0, 0),),
            )

    findings: list[Finding] = []
    for raw in (stdout or "").splitlines():
        m = _MYPY_LINE.match(raw.strip())
        if not m:
            continue
        if m.group("sev") != "error":
            continue  # notes / warnings don't fail the stage
        findings.append(
            Finding(
                tool="mypy",
                code=m.group("code") or "",
                message=m.group("msg"),
                lineno=int(m.group("line")),
                col=int(m.group("col")),
            )
        )
    return StaticCheckReport(ok=not findings, findings=tuple(findings))


# ── combined (stages 2 + 3) ────────────────────────────────────────────────────


def run_static_checks(source: str) -> StaticCheckReport:
    """Run ruff then mypy and merge. ``ok`` iff both pass; ``available``
    iff both checkers were invocable. Both run regardless of the other's
    result so the generator gets all findings in one pass."""
    ruff = run_ruff(source)
    mypy = run_mypy(source)
    return StaticCheckReport(
        ok=ruff.ok and mypy.ok,
        available=ruff.available and mypy.available,
        findings=ruff.findings + mypy.findings,
    )
