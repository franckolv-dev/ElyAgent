# =============================================================================
# @project    ELY — Exactly Like You
# @file       sandbox/runner/wrapper.py
# @brief      Sprint 4b V3 J2.c — child-process wrapper that actually runs the
#             generated python_tool.
#
#             This is the script the runner's subprocess executes with
#             `python -S`. It loads the spec JSON (passed via stdin), execs
#             the user source, calls the target function, and prints a
#             single JSON result on stdout. Stderr stays raw (any traceback
#             written by the source goes there).
#
#             Read by the parent FastAPI server (server.py) via
#             asyncio.create_subprocess_exec. The parent enforces the wall
#             clock; this wrapper just enforces the inner CPU/memory limits
#             via setrlimit before exec'ing user code.
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import json
import os
import resource
import signal
import sys
import traceback
from typing import Any


# Hard limits applied before user code runs. The parent FastAPI server reads
# them from env vars (set in the docker-compose service definition), so they
# can be tuned without rebuilding the image.
def _apply_rlimits() -> None:
    cpu_s = int(os.environ.get("ELY_SANDBOX_CPU_SECONDS", "10"))
    mem_b = int(os.environ.get("ELY_SANDBOX_MEM_BYTES", str(256 * 1024 * 1024)))
    # CPU: SIGXCPU at soft, SIGKILL at hard.
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    # AS = virtual address space ceiling. The Docker mem_limit is the harder
    # wall — this is just earlier signalling.
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_b, mem_b))
    except (ValueError, OSError):
        # macOS dev hosts don't honour RLIMIT_AS reliably. CI runs Linux so the
        # cap is real there; degrade silently elsewhere.
        pass
    # Forbid creating new files (only /tmp tmpfs is writable anyway; this is
    # belt + braces against accidentally piling up artefacts).
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ValueError, OSError):
        pass


def _safe_json(value: Any) -> tuple[bool, str]:
    """Return (json_serialisable, json_text_or_repr)."""
    try:
        text = json.dumps(value, ensure_ascii=False)
        return True, text
    except (TypeError, ValueError):
        return False, repr(value)[:2000]


def main() -> None:
    # Spec is small (the source + kwargs); read all of stdin.
    raw = sys.stdin.read()
    try:
        spec = json.loads(raw)
        source: str = spec["source"]
        func_name: str = spec["func_name"]
        kwargs: dict = spec.get("kwargs") or {}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"outcome": "error", "detail": f"bad spec: {exc}"}))
        sys.exit(0)

    _apply_rlimits()

    # The runner is "best-effort" with respect to async functions: V3.0 ships
    # sync tools only. Async support can land in V3.x without breaking the
    # wire format (just an extra outcome branch).
    ns: dict[str, Any] = {"__name__": "ely_generated_tool"}
    try:
        exec(compile(source, "<ely_generated_tool>", "exec"), ns, ns)
    except Exception as exc:  # noqa: BLE001 — any user-code exception → report
        print(json.dumps({
            "outcome": "raised",
            "stage": "import",
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[:4000],
        }))
        return

    target = ns.get(func_name)
    if not callable(target):
        print(json.dumps({
            "outcome": "error",
            "detail": f"function {func_name!r} not found or not callable",
        }))
        return

    try:
        result = target(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "outcome": "raised",
            "stage": "call",
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[:4000],
        }))
        return

    ok, payload = _safe_json(result)
    if ok:
        print(json.dumps({"outcome": "returned", "result_json": payload}))
    else:
        print(json.dumps({"outcome": "nonserializable", "result_repr": payload}))


if __name__ == "__main__":
    # Make the process a leader of its own group so a parent kill -9 hits the
    # whole subtree (subprocess.Popen with start_new_session already does this;
    # belt + braces if anyone runs this script directly).
    try:
        os.setsid()
    except OSError:
        pass
    # SIGXCPU is the polite soft-CPU-limit signal; turn it into a clean exit
    # so the JSON outcome can still get out before SIGKILL lands.
    signal.signal(signal.SIGXCPU, lambda *_a: sys.exit(0))
    main()
