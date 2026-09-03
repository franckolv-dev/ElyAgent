# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/smoke_sandbox.py
# @brief      Sprint 4b V2 J4 — smoke-execution sandbox for generated @tool
#             code (stage 4 of the validation pipeline).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Stage 4 of the V2 validation pipeline — run the generated tool once,
isolated, under resource limits (design note J0 §3.3).

After code_guard (stage 1) + ruff/mypy (stages 2-3) pass *statically*,
this stage actually EXECUTES the tool once on a sample input to catch
what static analysis can't: it crashes, hangs, eats CPU/memory, or
returns something non-serializable. This is where the J0 §3.2 residual
risk (ReDoS / runaway allocation) is contained — by RLIMIT + wall-clock
timeout, not by static inspection.

Isolation reuses the shared subprocess hardening (services.env_filter) :
``python -S`` (no site.py → backend/ not importable), scrubbed env (no
secrets), HOME redirected, PYTHONPATH = staging dir only, ``setsid`` +
process-group kill. On top, this stage adds RLIMIT_CPU + RLIMIT_AS and a
parent-side wall-clock timeout.

Network egress is NOT jailed at the kernel here — it doesn't need to be
in V2: code_guard already forbids ``socket``/``urllib``/``requests``
imports, so guard-passed source cannot open a socket. Kernel network
namespacing is a V3-Docker concern (when arbitrary I/O is allowed).
**Precondition: the source must already have passed code_guard.**

The tool is exec'd with no-op stubs for the ``@tool`` / ``@register``
decorators and ``Domain`` / ``InjectedToolArg`` symbols, so it stays a
plain (possibly async) function callable without importing real
langchain/app. Composition calls to *other* ELY tools are out of scope
for J4 (they need a stubbed dispatcher — J6/J7); J4 smoke targets
pure-computation (N2) tools.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Reuse the Sprint 2.7 hardening — single source of truth for env
# scrubbing + process-group kill.
from app.services.env_filter import (
    SAFE_ENV_PREFIXES,
    SECRET_SUBSTRINGS,
    filter_safe_env,
    kill_process_group,
)


# ── Result type ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SmokeReport:
    """Outcome of one smoke execution.

    ``outcome`` ∈ {returned, raised, nonserializable, timeout, crashed,
    error}. ``ok`` is True only for ``returned``."""

    ok: bool
    outcome: str
    detail: str = ""
    result_repr: str = ""
    duration_ms: int = 0


# ── Tool-function detection ────────────────────────────────────────────────────


def detect_tool_func(source: str) -> str | None:
    """Return the name of the function to smoke-run.

    Preference: a top-level (async) function decorated with ``@tool`` or
    ``@register``; else the only top-level function; else None.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    funcs = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not funcs:
        return None

    def _decorated(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for dec in fn.decorator_list:
            name = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(name, ast.Name) and name.id in {"tool", "register"}:
                return True
        return False

    for fn in funcs:
        if _decorated(fn):
            return fn.name
    if len(funcs) == 1:
        return funcs[0].name
    return None


# ── The child runner (static — reads its inputs from smoke_in.json) ───────────
# No interpolation: keeps quoting trivial and the script auditable.

_RUNNER_SOURCE = r'''
import asyncio
import inspect
import json
import sys
import types


def _identity(*args, **kwargs):
    # Supports @tool, @tool(...), @register(...): bare decorator or factory.
    if len(args) == 1 and not kwargs and callable(args[0]):
        return args[0]
    def _wrap(fn):
        return fn
    return _wrap


class _Domain:
    def __getattr__(self, name):
        return name


def _stub(name, attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


# Inject no-op stand-ins so the @tool/@register scaffolding imports resolve
# without pulling real langchain/app — the function stays plain + callable.
sys.modules["langchain_core"] = types.ModuleType("langchain_core")
sys.modules["langchain_core.tools"] = _stub(
    "langchain_core.tools",
    {"tool": _identity, "InjectedToolArg": object, "StructuredTool": object},
)
async def _async_stub(*args, **kwargs):
    # Composition tools do `await call_tool(...)`. The sandbox has no real
    # registry, so it cannot reproduce a tool's SEMANTICS — but it can and
    # must reproduce its TYPE CONTRACT: every ELY tool returns a
    # human-readable str, never a dict/list. Returning {} here (the old
    # behaviour) actively hid the most common generated-tool bug —
    # `result[0].get("id")` — which then crashed in production.
    # The shape mimics drive_list_files: a listing with an "ID :" line.
    return (
        "1 fichier(s):\n\n"
        "• exemple.pdf (application/pdf)\n"
        "  Modifie: 2026-07-22T10:00:00Z | Taille: 12 Ko\n"
        "  ID : 1AbCdEfGhIjKlMnOpQrStUvWxYz"
    )


sys.modules["app"] = types.ModuleType("app")
sys.modules["app.skills"] = types.ModuleType("app.skills")
sys.modules["app.skills.decorator"] = _stub("app.skills.decorator", {"register": _identity})
sys.modules["app.skills.base"] = _stub("app.skills.base", {"Domain": _Domain()})
sys.modules["app.services"] = types.ModuleType("app.services")
sys.modules["app.services.learning"] = types.ModuleType("app.services.learning")
sys.modules["app.services.learning.learned_tool_dispatch"] = _stub(
    "app.services.learning.learned_tool_dispatch", {"call_tool": _async_stub}
)

with open("smoke_in.json", encoding="utf-8") as fh:
    spec = json.load(fh)

source = spec["source"]
func_name = spec["func_name"]
kwargs = spec.get("kwargs") or {}

out = {"outcome": "error", "detail": "uninitialised"}
try:
    ns = {}
    exec(compile(source, "generated_tool.py", "exec"), ns, ns)
    target = ns.get(func_name)
    if not callable(target):
        out = {"outcome": "error", "detail": "function %r not found" % func_name}
    else:
        if inspect.iscoroutinefunction(target):
            res = asyncio.run(target(**kwargs))
        else:
            res = target(**kwargs)
        try:
            json.dumps(res)
            out = {"outcome": "returned", "result_repr": repr(res)[:500]}
        except (TypeError, ValueError):
            out = {"outcome": "nonserializable", "result_repr": repr(res)[:500]}
except Exception as exc:  # noqa: BLE001 — any tool failure becomes a report
    out = {"outcome": "raised", "detail": ("%s: %s" % (type(exc).__name__, exc))[:500]}

with open("smoke_out.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh)
'''


# ── preexec (POSIX): setsid + resource limits ──────────────────────────────────


def _make_preexec(cpu_seconds: int, mem_bytes: int):
    if os.name == "nt":  # pragma: no cover — sandbox unsupported on Windows
        return None

    def _preexec() -> None:
        os.setsid()  # own process group → clean kill
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        except (ValueError, OSError):
            pass
        if mem_bytes > 0:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                # RLIMIT_AS is not reliably enforced on macOS — the
                # wall-clock timeout is the cross-platform backstop.
                pass

    return _preexec


# ── Public API ─────────────────────────────────────────────────────────────────


def smoke_run(
    source: str,
    *,
    func_name: str | None = None,
    kwargs: dict | None = None,
    cpu_seconds: int = 2,
    mem_mb: int = 1024,
    timeout_s: float = 5.0,
) -> SmokeReport:
    """Execute ``source``'s tool function once in an isolated subprocess.

    Precondition: ``source`` has already passed code_guard. Returns a
    :class:`SmokeReport`; never raises for tool-level failures (they
    become ``outcome``).
    """
    target = func_name or detect_tool_func(source)
    if target is None:
        return SmokeReport(
            ok=False,
            outcome="error",
            detail="could not locate a tool function to run",
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="ely_smoke_"))
    start = time.monotonic()
    try:
        home_dir = tmpdir / "home"
        home_dir.mkdir()
        (tmpdir / "runner.py").write_text(_RUNNER_SOURCE, encoding="utf-8")
        (tmpdir / "smoke_in.json").write_text(
            json.dumps({"source": source, "func_name": target, "kwargs": kwargs or {}}),
            encoding="utf-8",
        )

        env = filter_safe_env(
            safe_prefixes=SAFE_ENV_PREFIXES,
            secret_substrings=SECRET_SUBSTRINGS,
        )
        env["HOME"] = str(home_dir)
        env["PYTHONPATH"] = str(tmpdir)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-S", "runner.py"],
            cwd=str(tmpdir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=_make_preexec(cpu_seconds, mem_mb * 1024 * 1024),
        )

        killed_on_timeout = False
        deadline = start + timeout_s
        while True:
            if proc.poll() is not None:
                break
            if time.monotonic() >= deadline:
                killed_on_timeout = True
                kill_process_group(proc, grace=1.0)
                break
            time.sleep(0.02)

        duration_ms = int((time.monotonic() - start) * 1000)

        out_path = tmpdir / "smoke_out.json"
        if out_path.exists():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = None
            if isinstance(data, dict) and "outcome" in data:
                outcome = data["outcome"]
                return SmokeReport(
                    ok=(outcome == "returned"),
                    outcome=outcome,
                    detail=data.get("detail", ""),
                    result_repr=data.get("result_repr", ""),
                    duration_ms=duration_ms,
                )

        # No result file → the child was killed or died before writing.
        if killed_on_timeout:
            return SmokeReport(
                ok=False,
                outcome="timeout",
                detail=f"wall-clock timeout after {timeout_s}s — process group killed",
                duration_ms=duration_ms,
            )
        return SmokeReport(
            ok=False,
            outcome="crashed",
            detail=(
                f"process exited (code {proc.returncode}) without a result — "
                "likely RLIMIT_CPU/RLIMIT_AS kill or a hard crash"
            ),
            duration_ms=duration_ms,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
