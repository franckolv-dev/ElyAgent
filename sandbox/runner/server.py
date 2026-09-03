# =============================================================================
# @project    ELY — Exactly Like You
# @file       sandbox/runner/server.py
# @brief      Sprint 4b V3 J2.c — sandbox runner HTTP service.
#
#             Exposes POST /run, /healthz, GET /. Receives a job spec from
#             the backend (source + func_name + kwargs + timeout_s), spawns
#             a fresh `python -S wrapper.py` subprocess, captures its single
#             JSON outcome line, returns it as the response body.
#
#             The HTTP surface is tiny on purpose: this service is
#             internal-only (binds on sandbox-net) and runs only ELY's own
#             code. Hardening (read-only rootfs, dropped capabilities,
#             pids_limit, mem_limit) is enforced by the docker-compose
#             service definition.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("ely-sandbox-runner")

app = FastAPI(title="ely-sandbox-runner", version="0.1.0")

WRAPPER_PATH = Path(__file__).with_name("wrapper.py").resolve()

# The runner itself runs INSIDE a venv (/opt/runner-venv) that holds fastapi +
# uvicorn. The generated user code must run on the SYSTEM Python instead —
# the one with the curated allow-list (httpx, bs4, lxml). We therefore pin
# the absolute path explicitly instead of using sys.executable (which would
# point at the runner venv via $PATH).
USER_PYTHON = os.environ.get("ELY_SANDBOX_USER_PYTHON", "/usr/local/bin/python")


def _discover_user_site_packages() -> str:
    """Path (colon-separated) of the user-Python's site-packages.

    Needed because we spawn subprocesses with `python -S`, which deliberately
    skips `site.py` init — without this PYTHONPATH the curated libs (httpx,
    bs4, lxml) installed in /usr/local/lib/python3.x/site-packages aren't
    importable. We discover the path once at boot rather than hard-coding
    a specific Python version.
    """
    import subprocess

    try:
        out = subprocess.check_output([
            USER_PYTHON, "-c",
            "import site, os; print(os.pathsep.join(site.getsitepackages()))",
        ], text=True, timeout=5).strip()
        return out
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("could not discover user site-packages: %s", exc)
        return ""


USER_SITE_PACKAGES = _discover_user_site_packages()
logger.info("user site-packages: %s", USER_SITE_PACKAGES or "(none)")

DEFAULT_TIMEOUT_S = 8
MAX_TIMEOUT_S = 60
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 16 * 1024


# Sprint 4b V3 J6.b.1 — bounds on `secrets`. A label that fits the V4
# decl gate (`[a-z][a-z0-9_]{2,63}`) and a value cap that fits any
# realistic PAT / API key without ballooning request size.
MAX_SECRET_LABELS = 32
MAX_SECRET_VALUE_BYTES = 4 * 1024  # 4 KB per secret
_SECRET_LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class RunRequest(BaseModel):
    source: str = Field(
        ...,
        min_length=1,
        max_length=200_000,
        description="The full module source of the python_tool (already guarded + smoke'd by the upstream validators).",
    )
    func_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Name of the callable to invoke after exec'ing `source`.",
    )
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword args passed to the callable.",
    )
    timeout_s: int = Field(
        DEFAULT_TIMEOUT_S,
        ge=1,
        le=MAX_TIMEOUT_S,
        description="Wall-clock timeout for the whole run. The wrapper also caps CPU via RLIMIT.",
    )
    # Sprint 4b V3 J6.b.1 — secrets the tool can read inside the sandbox.
    # Labels match the V3 decl gate; values are arbitrary (the caller has
    # already resolved them from Vault). The wrapper injects them as a
    # `_SECRETS: dict[str, str]` global + a `get_secret(label) -> str`
    # helper, both available to the tool's source. We do NOT push them as
    # env vars: the user code can't `import os` even under profile=io
    # (code_guard's import allow-list omits `os` deliberately), so an env
    # var would be inert anyway and a leak risk to any future child.
    secrets: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-call secrets bag. Labels must match [a-z][a-z0-9_]{2,63}; "
            "values are capped at 4 KB each, max 32 entries per call. "
            "Available to the tool source as `_SECRETS[label]` or "
            "`get_secret(label)` (the latter returns '' for unknown labels)."
        ),
    )

    @field_validator("secrets")
    @classmethod
    def _validate_secrets(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            return v
        if len(v) > MAX_SECRET_LABELS:
            raise ValueError(
                f"too many secrets ({len(v)} > {MAX_SECRET_LABELS})",
            )
        for label, value in v.items():
            if not isinstance(label, str) or not _SECRET_LABEL_RE.match(label):
                raise ValueError(
                    f"invalid secret label {label!r} (must match "
                    f"[a-z][a-z0-9_]{{2,63}})",
                )
            if not isinstance(value, str):
                raise ValueError(
                    f"secret {label!r} value must be a string (got {type(value).__name__})",
                )
            if len(value.encode("utf-8")) > MAX_SECRET_VALUE_BYTES:
                raise ValueError(
                    f"secret {label!r} value exceeds {MAX_SECRET_VALUE_BYTES} bytes",
                )
        return v


class RunResponse(BaseModel):
    # `outcome` mirrors the SmokeReport vocab used by the in-process validator
    # (`smoke_sandbox.py`), so the backend can plug this into the same code
    # path that today handles smoke results.
    outcome: str  # returned | raised | nonserializable | timeout | crashed | error
    duration_s: float
    # Present when outcome=returned: the JSON-encoded result.
    result_json: str | None = None
    # Present when outcome=raised/nonserializable/error.
    detail: str | None = None
    stage: str | None = None
    error: str | None = None
    trace: str | None = None
    result_repr: str | None = None
    # Always present: captured streams, size-capped.
    stdout: str = ""
    stderr: str = ""


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "ely-sandbox-runner", "ok": "true"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Readiness probe — the wrapper script must exist and be readable.

    Used by the compose healthcheck. Intentionally does NOT spawn a real
    subprocess (that would slow the probe down + log noise)."""
    if not WRAPPER_PATH.is_file():
        raise HTTPException(500, f"wrapper not found at {WRAPPER_PATH}")
    return {"status": "ok"}


# B-10 (revue 2026-06-10) — borne de concurrence. Sans elle, N runs
# simultanés (N users) cumulent N × ELY_SANDBOX_MEM_BYTES (256 Mio chacun)
# dans un conteneur plafonné à 512 Mio → OOM-kill du conteneur ENTIER, tous
# les runs de tous les users échouent d'un coup. Défaut 2 = exactement le
# cap mémoire ; au-delà de la file d'attente bornée, on répond 503 (le
# client retombe sur son chemin « sandbox indisponible » au lieu de geler).
_MAX_CONCURRENCY = int(os.environ.get("ELY_SANDBOX_MAX_CONCURRENCY", "2"))
_QUEUE_TIMEOUT_S = float(os.environ.get("ELY_SANDBOX_QUEUE_TIMEOUT_S", "10"))
_RUN_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENCY)


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    """Execute one python_tool job in a fresh subprocess."""
    try:
        await asyncio.wait_for(_RUN_SEMAPHORE.acquire(), timeout=_QUEUE_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            503,
            f"sandbox busy — {_MAX_CONCURRENCY} concurrent runs already in "
            f"flight and queue wait exceeded {_QUEUE_TIMEOUT_S}s",
        )
    try:
        return await _run_subprocess(req)
    finally:
        _RUN_SEMAPHORE.release()


async def _run_subprocess(req: RunRequest) -> RunResponse:
    # Tools may legitimately do network I/O; ensure the proxy URL the
    # docker-compose passes via env is propagated to the child (httpx,
    # urllib, requests all honour HTTP(S)_PROXY).
    env = {
        # Bare minimum — strip everything else. The proxy URL is what makes
        # outbound HTTP work at all (sandbox-net has no other Internet route).
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "ELY_SANDBOX_CPU_SECONDS": os.environ.get("ELY_SANDBOX_CPU_SECONDS", "10"),
        "ELY_SANDBOX_MEM_BYTES": os.environ.get(
            "ELY_SANDBOX_MEM_BYTES", str(256 * 1024 * 1024),
        ),
    }
    # Expose the curated libs to the `-S` subprocess (which skips site.py and
    # would otherwise see an empty site-packages).
    if USER_SITE_PACKAGES:
        env["PYTHONPATH"] = USER_SITE_PACKAGES
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        if var in os.environ:
            env[var] = os.environ[var]

    import json as _json
    # `secrets` only enters the wrapper via stdin (never env), so a leak path
    # via /proc/<runner-pid>/environ doesn't exist. The wrapper exposes them
    # to user code as a `_SECRETS` dict + `get_secret` helper.
    spec_payload = _json.dumps({
        "source": req.source,
        "func_name": req.func_name,
        "kwargs": req.kwargs,
        "secrets": req.secrets,
    })

    t0 = time.perf_counter()
    # `python -S` skips the site-packages auto-init — slightly faster startup
    # and removes one big source of accidental side-effects.
    try:
        proc = await asyncio.create_subprocess_exec(
            USER_PYTHON, "-S", str(WRAPPER_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd="/tmp",
            start_new_session=True,  # so we can SIGKILL the whole group
        )
    except OSError as exc:
        # Should only happen on a busted image or out-of-pids — surface as 500.
        logger.exception("subprocess spawn failed")
        raise HTTPException(500, f"spawn failed: {exc}")

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=spec_payload.encode()),
            timeout=req.timeout_s,
        )
    except asyncio.TimeoutError:
        _kill_group(proc.pid)
        await proc.wait()
        duration = time.perf_counter() - t0
        return RunResponse(
            outcome="timeout",
            duration_s=round(duration, 3),
            detail=f"wall-clock exceeded {req.timeout_s}s",
        )

    duration = time.perf_counter() - t0
    stdout = stdout_b.decode("utf-8", errors="replace")[:MAX_STDOUT_BYTES]
    stderr = stderr_b.decode("utf-8", errors="replace")[:MAX_STDERR_BYTES]

    if proc.returncode != 0:
        # The wrapper catches and JSON-reports exceptions before exit, so a
        # non-zero RC means something killed it from outside (RLIMIT, OOM,
        # signal). Surface as 'crashed' so the caller can treat it as an
        # unbounded failure rather than a structured exception.
        return RunResponse(
            outcome="crashed",
            duration_s=round(duration, 3),
            detail=f"wrapper exit code {proc.returncode}",
            stdout=stdout,
            stderr=stderr,
        )

    # The wrapper prints a single JSON line — last non-empty line of stdout.
    line = next(
        (ln for ln in reversed(stdout.splitlines()) if ln.strip()),
        "",
    )
    try:
        payload = _json.loads(line)
    except _json.JSONDecodeError:
        return RunResponse(
            outcome="error",
            duration_s=round(duration, 3),
            detail="wrapper produced no JSON outcome",
            stdout=stdout,
            stderr=stderr,
        )

    return RunResponse(
        outcome=payload.get("outcome", "error"),
        duration_s=round(duration, 3),
        result_json=payload.get("result_json"),
        result_repr=payload.get("result_repr"),
        detail=payload.get("detail"),
        stage=payload.get("stage"),
        error=payload.get("error"),
        trace=payload.get("trace"),
        # Strip the JSON outcome line from stdout in the response — keep only
        # whatever the user code printed before it. Easier for debug.
        stdout=stdout.replace(line, "", 1).strip(),
        stderr=stderr,
    )


def _kill_group(pid: int) -> None:
    """SIGKILL the entire process group (set up via start_new_session above)."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError) as exc:
        logger.debug("kill_group(%s) failed: %s", pid, exc)
    # Belt + braces: also wipe any orphan files the wrapper might have left in
    # /tmp. tmpfs survives only as long as the container, but we still want a
    # tidy state across runs.
    try:
        for sub in Path("/tmp").iterdir():
            if sub.name.startswith("ely-"):
                shutil.rmtree(sub, ignore_errors=True)
    except OSError:
        pass
